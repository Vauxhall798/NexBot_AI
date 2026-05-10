from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import requests
import os
import json
import uuid
import time
import hashlib
import sqlite3
from datetime import datetime
from typing import Optional
import re
import io
import contextlib
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False

# Optional heavy deps — graceful fallback
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import psycopg2
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

try:
    import pymssql
    PYMSSQL_AVAILABLE = True
except ImportError:
    PYMSSQL_AVAILABLE = False

load_dotenv()

app = Flask(__name__)

CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS", "DELETE"],
        "allow_headers": ["Content-Type", "Authorization", "X-API-Key", "X-Domain"]
    }
})

# ── Config ───────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
GROQ_MODEL   = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
UPLOAD_DIR   = os.getenv('UPLOAD_DIR', 'uploads')
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', 'downloads')
CACHE_TTL    = int(os.getenv('DATA_CACHE_TTL', 300))

# ── Plugin Registration ──────────────────────────────────────────────────────
# Master password that users must supply to register as a plugin consumer.
# Set this in your .env file. Anyone who knows this password can self-register.
ADMIN_PASSWORD   = os.getenv('NEXBOT_ADMIN_PASSWORD', 'changeme_super_secret')
LICENSE_DB_PATH  = os.getenv('LICENSE_DB_PATH', 'data/licenses.db')

# Groq generation params
GROQ_PARAMS_FAST = {'temperature': 0.3, 'max_tokens': 2000,  'top_p': 0.8}
GROQ_PARAMS_DASH = {'temperature': 0.2, 'max_tokens': 6000, 'top_p': 0.8}

ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}

os.makedirs(UPLOAD_DIR,   exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LICENSE_DB_PATH) or '.', exist_ok=True)

# ── In-memory stores ──────────────────────────────────────────────────────────
VALID_API_KEYS = {
    'test_key_123': {'user': 'test_user',  'plan': 'free',         'limit': 100,  'status': 'active'},
    'demo_key_456': {'user': 'demo_user',  'plan': 'starter',      'limit': 1000, 'status': 'active'},
    'aitc_test_12345678901234567890123456789012': {'user': 'test_user_2', 'plan': 'professional', 'limit': 5000, 'status': 'active'},
}

# {source_id: {...}}
DATA_SOURCES: dict = {}

# Response cache
RESPONSE_CACHE: dict = {}
RESPONSE_CACHE_TTL = 120


# ── License Database ─────────────────────────────────────────────────────────

def _init_license_db():
    """Create the licenses SQLite table if it doesn't exist."""
    conn = sqlite3.connect(LICENSE_DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS licenses (
        api_key    TEXT PRIMARY KEY,
        user_name  TEXT NOT NULL,
        email      TEXT,
        plan       TEXT NOT NULL DEFAULT 'free',
        query_limit INTEGER NOT NULL DEFAULT 100,
        status     TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL,
        last_used  TEXT
    )''')
    conn.commit()
    conn.close()

_init_license_db()


def _seed_keys_from_env():
    """
    Auto-seed persistent API keys from the NEXBOT_SEED_KEYS env variable.
    This ensures important keys survive Render redeploys (ephemeral storage).
    Format: JSON array of objects, e.g.
    [{"key":"nxb_abc123","name":"Vivek","email":"v@test.com","plan":"starter","limit":1000}]
    """
    raw = os.getenv('NEXBOT_SEED_KEYS', '').strip()
    if not raw:
        return
    try:
        seeds = json.loads(raw)
        conn = sqlite3.connect(LICENSE_DB_PATH)
        seeded = 0
        for s in seeds:
            api_key = s.get('key', '')
            if not api_key:
                continue
            # Only insert if key doesn't already exist
            exists = conn.execute('SELECT 1 FROM licenses WHERE api_key = ?', (api_key,)).fetchone()
            if not exists:
                conn.execute(
                    'INSERT INTO licenses (api_key, user_name, email, plan, query_limit, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (api_key, s.get('name', 'seeded_user'), s.get('email', ''),
                     s.get('plan', 'free'), s.get('limit', 100), 'active', datetime.now().isoformat())
                )
                seeded += 1
        conn.commit()
        conn.close()
        if seeded:
            print(f"🔑  Auto-seeded {seeded} API key(s) from NEXBOT_SEED_KEYS.")
    except Exception as e:
        print(f"⚠️  Could not seed keys from NEXBOT_SEED_KEYS: {e}")

_seed_keys_from_env()


def _db_get_key(api_key: str) -> Optional[dict]:
    """Look up an API key in the SQLite license database."""
    conn = sqlite3.connect(LICENSE_DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM licenses WHERE api_key = ?', (api_key,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        'user':   row['user_name'],
        'plan':   row['plan'],
        'limit':  row['query_limit'],
        'status': row['status'],
    }


def _db_create_key(user_name: str, email: str = '', plan: str = 'free', limit: int = 100) -> str:
    """Generate a new API key and insert it into the license database."""
    api_key = f"nxb_{uuid.uuid4().hex}"
    conn = sqlite3.connect(LICENSE_DB_PATH)
    conn.execute(
        'INSERT INTO licenses (api_key, user_name, email, plan, query_limit, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (api_key, user_name, email, plan, limit, 'active', datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return api_key


def _db_list_keys() -> list:
    """Return all registered API keys (admin view)."""
    conn = sqlite3.connect(LICENSE_DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT api_key, user_name, email, plan, query_limit, status, created_at, last_used FROM licenses ORDER BY created_at DESC').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _db_revoke_key(api_key: str) -> bool:
    """Deactivate a license key."""
    conn = sqlite3.connect(LICENSE_DB_PATH)
    cur = conn.execute('UPDATE licenses SET status = ? WHERE api_key = ?', ('revoked', api_key))
    conn.commit()
    affected = cur.rowcount
    conn.close()
    return affected > 0


def _db_touch_key(api_key: str):
    """Update last_used timestamp for an API key."""
    try:
        conn = sqlite3.connect(LICENSE_DB_PATH)
        conn.execute('UPDATE licenses SET last_used = ? WHERE api_key = ?', (datetime.now().isoformat(), api_key))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def verify_api_key():
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    if not api_key:
        api_key = request.headers.get('X-API-Key', '')
    if not api_key:
        return None, jsonify({'success': False, 'error': 'API key required'}), 401

    # Check hardcoded keys first (backward compat), then SQLite DB
    user = VALID_API_KEYS.get(api_key)
    if not user:
        user = _db_get_key(api_key)
    if not user:
        return None, jsonify({'success': False, 'error': 'Invalid API key'}), 401
    if user['status'] != 'active':
        return None, jsonify({'success': False, 'error': 'Inactive subscription'}), 402

    # Track usage timestamp
    _db_touch_key(api_key)
    return user, None, None


def _groq_client():
    """Return a configured Groq client (lazy import)."""
    from groq import Groq
    return Groq(api_key=GROQ_API_KEY)


def groq_prompt(prompt: str, params: dict = None) -> str:
    """Non-streaming Groq call — returns full response string."""
    try:
        p = params or GROQ_PARAMS_FAST
        client = _groq_client()
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            **p
        )
        return completion.choices[0].message.content or ''
    except Exception as e:
        raise Exception(f"Groq API error: {e}")


def groq_stream(prompt: str, params: dict = None):
    """Generator that yields text tokens from Groq streaming API."""
    p = params or GROQ_PARAMS_FAST
    client = _groq_client()
    stream = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{'role': 'user', 'content': prompt}],
        stream=True,
        **p
    )
    for chunk in stream:
        token = chunk.choices[0].delta.content or ''
        if token:
            yield token


def check_groq_status() -> dict:
    """Verify the Groq API key is set and reachable."""
    if not GROQ_API_KEY:
        return {'ready': False, 'error': 'GROQ_API_KEY not set in .env'}
    return {'ready': True, 'model': GROQ_MODEL}


def _cache_key(message: str, source_id: Optional[str]) -> str:
    raw = f"{message.lower().strip()}|{source_id or 'none'}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached(key: str) -> Optional[str]:
    entry = RESPONSE_CACHE.get(key)
    if entry and time.time() < entry['expires_at']:
        return entry['response']
    return None


def _set_cached(key: str, response: str) -> None:
    RESPONSE_CACHE[key] = {'response': response, 'expires_at': time.time() + RESPONSE_CACHE_TTL}


def dataframe_to_source(df, name: str, source_type: str) -> dict:
    """Convert a pandas DataFrame into a DATA_SOURCES entry."""
    source_id = str(uuid.uuid4())[:8]
    schema = {}
    for col in df.columns:
        dtype = str(df[col].dtype)
        schema[col] = 'numeric' if 'int' in dtype or 'float' in dtype else 'text'
    data = df.head(100).fillna('').to_dict(orient='records')
    entry = {
        'id':           source_id,
        'name':         name,
        'type':         source_type,
        'data':         data,
        'schema':       schema,
        'record_count': len(df),
        'created_at':   datetime.now().isoformat(),
        'expires_at':   time.time() + CACHE_TTL,
        'df':           df,
    }
    DATA_SOURCES[source_id] = entry
    return entry


def get_active_source(source_id: str = None) -> Optional[dict]:
    """Return a data source by id, or the most recently created one."""
    if source_id:
        return DATA_SOURCES.get(source_id)
    if not DATA_SOURCES:
        return None
    return sorted(DATA_SOURCES.values(), key=lambda s: s['created_at'], reverse=True)[0]


def data_to_text(source: dict) -> str:
    """Render first 50 rows of a data source as a markdown table for the prompt."""
    data   = source.get('data', [])[:50]
    schema = source.get('schema', {})
    if not data:
        return "No data available."
    # Limit to 5 rows to keep prompt small & fast
    data = data[:5]
    headers = list(schema.keys()) or list(data[0].keys())
    # Limit headers if there are too many columns
    if len(headers) > 30:
        headers = headers[:30]
        
    lines   = ["| " + " | ".join(headers) + " |",
               "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in data:
        lines.append("| " + " | ".join(str(row.get(h, ''))[:50] for h in headers) + " |")
        
    result_text = "\n".join(lines) + f"\n\n({source['record_count']} total rows)"
    
    # Hard cap length to avoid 400 errors from Groq API
    if len(result_text) > 4000:
        result_text = result_text[:4000] + "\n...[truncated due to length]..."
        
    return result_text


def get_all_sources_text() -> str:
    """Combine previews of all loaded data sources for a holistic analysis."""
    if not DATA_SOURCES:
        return "No data loaded."
    texts = []
    for s in DATA_SOURCES.values():
        texts.append(f"Table: {s['name']}\n{data_to_text(s)}")
    combined = "\n\n".join(texts)
    
    # Cap total combined length to ~25,000 chars to fit in token limits safely
    if len(combined) > 25000:
        combined = combined[:25000] + "\n...[truncated due to length]..."
    return combined

def extract_python_code(text: str) -> str:
    match = re.search(r'```python\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        return match.group(1)
    return text.strip()

def execute_pandas_code(dfs: dict, code: str) -> str:
    """Execute AI-generated pandas code against loaded DataFrames.
    
    We merge all DataFrames + pandas into a single namespace dict passed as
    both globals and locals to exec().  This avoids Python's known scoping
    quirk where exec(code, {}, locals_dict) fails to resolve bare variable
    names like `ItineraryMaster`.
    """
    import numpy as np
    namespace = {'pd': pd, 'np': np, '__builtins__': __builtins__}
    namespace.update(dfs)          # e.g. ItineraryMaster=df, VendorMaster=df
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            exec(code, namespace)
        result = output.getvalue()
        if not result.strip():
            return "Code executed successfully but produced no output."
        return result.strip()
    except Exception as e:
        return f"Error executing code: {e}"

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'model': GROQ_MODEL,
        'data_sources': len(DATA_SOURCES),
        'sql_status': SQL_ERROR,
        'pg_status': PG_ERROR,
        'service': 'AI Data Chatbot API (Groq)',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/v1/verify', methods=['POST', 'OPTIONS'])
def verify_license():
    if request.method == 'OPTIONS':
        return '', 204
    user, err, code = verify_api_key()
    if err:
        return err, code
    return jsonify({
        'valid': True,
        'subscription': {'plan': user['plan'], 'status': user['status']},
        'limits': {'monthly': user['limit'], 'current': 0, 'remaining': user['limit']},
    })


# ── Plugin Registration (password-protected) ─────────────────────────────────

@app.route('/api/v1/register', methods=['POST', 'OPTIONS'])
def register_plugin():
    """
    Password-protected self-registration.
    Users POST { "password": "...", "name": "...", "email": "..." }
    and receive a fresh API key they can use in the plugin embed snippet.
    """
    if request.method == 'OPTIONS':
        return '', 204

    body     = request.get_json() or {}
    password = body.get('password', '')
    name     = body.get('name', '').strip()
    email    = body.get('email', '').strip()
    plan     = body.get('plan', 'free')

    if not password:
        return jsonify({'success': False, 'error': 'Password is required'}), 400
    if not name:
        return jsonify({'success': False, 'error': 'Name is required'}), 400

    # Verify the master password
    if password != ADMIN_PASSWORD:
        return jsonify({'success': False, 'error': 'Invalid registration password'}), 403

    # Determine query limit based on plan
    plan_limits = {'free': 100, 'starter': 1000, 'professional': 5000, 'enterprise': 50000}
    limit = plan_limits.get(plan, 100)

    api_key = _db_create_key(user_name=name, email=email, plan=plan, limit=limit)

    # Build the embed snippet for the user
    server_url = request.host_url.rstrip('/')
    embed_snippet = f"""<!-- NexBot AI Plugin -->
<script src="{server_url}/plugin/chatbot-plugin.js"></script>
<script>
  document.addEventListener('DOMContentLoaded', () => {{
    new AITableChatbot({{
      apiEndpoint: '{server_url}',
      apiKey: '{api_key}'
    }});
  }});
</script>"""

    return jsonify({
        'success':       True,
        'api_key':       api_key,
        'plan':          plan,
        'query_limit':   limit,
        'embed_snippet': embed_snippet,
        'message':       f'Plugin registered for {name}. Paste the embed_snippet into your HTML to activate.',
    }), 201


@app.route('/api/v1/admin/keys', methods=['GET', 'DELETE', 'OPTIONS'])
def admin_keys():
    """
    Admin endpoint — requires the master password in the X-Admin-Password header.
    GET  → list all registered keys
    DELETE { "api_key": "..." } → revoke a key
    """
    if request.method == 'OPTIONS':
        return '', 204

    admin_pw = request.headers.get('X-Admin-Password', '')
    if admin_pw != ADMIN_PASSWORD:
        return jsonify({'success': False, 'error': 'Unauthorized — invalid admin password'}), 403

    if request.method == 'GET':
        keys = _db_list_keys()
        return jsonify({'success': True, 'total': len(keys), 'keys': keys})

    if request.method == 'DELETE':
        body    = request.get_json() or {}
        api_key = body.get('api_key', '')
        if not api_key:
            return jsonify({'success': False, 'error': 'api_key is required'}), 400
        revoked = _db_revoke_key(api_key)
        if revoked:
            return jsonify({'success': True, 'message': f'Key {api_key[:12]}... has been revoked'})
        return jsonify({'success': False, 'error': 'Key not found'}), 404


@app.route('/api/v1/plugin/embed', methods=['GET'])
def plugin_embed_info():
    """
    Public info endpoint — explains how to install the plugin.
    No auth required (it's the landing page for new users).
    """
    server_url = request.host_url.rstrip('/')
    return jsonify({
        'service': 'NexBot AI Plugin',
        'steps': [
            f'1. Register: POST {server_url}/api/v1/register with {{"password": "YOUR_PASSWORD", "name": "Your Name", "email": "you@example.com"}}',
            '2. Copy the embed_snippet from the response.',
            '3. Paste it into your website HTML (before </body>).',
            '4. Done! The NexBot chat widget will appear on your site.'
        ],
        'plugin_js_url': f'{server_url}/plugin/chatbot-plugin.js',
    })


# ── Serve the frontend (index.html + static assets) ─────────────────────────

@app.route('/', methods=['GET'])
def serve_index():
    """Serve the main frontend page."""
    return send_from_directory(os.path.abspath('.'), 'index.html')


@app.route('/style.css', methods=['GET'])
def serve_css():
    """Serve the stylesheet."""
    return send_from_directory(os.path.abspath('.'), 'style.css',
                               mimetype='text/css')


@app.route('/chatbot-plugin.js', methods=['GET'])
def serve_plugin_js_root():
    """Serve the chatbot plugin JS from the root path (used by index.html)."""
    return send_from_directory(os.path.abspath('.'), 'chatbot-plugin.js',
                               mimetype='application/javascript')


# ── Serve the plugin JS file (legacy plugin embed path) ──────────────────────

@app.route('/plugin/chatbot-plugin.js', methods=['GET'])
def serve_plugin_js():
    """Serve the chatbot plugin JavaScript file for remote embedding."""
    return send_from_directory(os.path.abspath('.'), 'chatbot-plugin.js',
                               mimetype='application/javascript')


# ── Data source endpoints ─────────────────────────────────────────────────────

@app.route('/api/v1/data/sources', methods=['GET', 'OPTIONS'])
def list_sources():
    if request.method == 'OPTIONS':
        return '', 204
    user, err, code = verify_api_key()
    if err:
        return err, code

    sources = [
        {'id': s['id'], 'name': s['name'], 'type': s['type'],
         'record_count': s['record_count'], 'created_at': s['created_at']}
        for s in DATA_SOURCES.values()
    ]
    return jsonify({'success': True, 'sources': sources})


@app.route('/api/v1/data/upload-file', methods=['POST', 'OPTIONS'])
def upload_file():
    if request.method == 'OPTIONS':
        return '', 204
    user, err, code = verify_api_key()
    if err:
        return err, code

    if not PANDAS_AVAILABLE:
        return jsonify({'success': False, 'error': 'pandas not installed on server'}), 500

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file part in request'}), 400

    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({'success': False, 'error': 'Invalid or unsupported file type (use CSV / XLSX)'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)

    try:
        ext = filename.rsplit('.', 1)[1].lower()
        df  = pd.read_csv(filepath) if ext == 'csv' else pd.read_excel(filepath)
        entry = dataframe_to_source(df, filename, 'file')
        return jsonify({
            'success':      True,
            'filename':     filename,
            'source_id':    entry['id'],
            'record_count': entry['record_count'],
            'schema':       entry['schema'],
            'preview':      entry['data'][:10],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Failed to parse file: {e}'}), 500


@app.route('/api/v1/data/connect-db', methods=['POST', 'OPTIONS'])
def connect_db():
    if request.method == 'OPTIONS':
        return '', 204
    user, err, code = verify_api_key()
    if err:
        return err, code

    if not PANDAS_AVAILABLE:
        return jsonify({'success': False, 'error': 'pandas not installed on server'}), 500

    body   = request.get_json() or {}
    db_type = body.get('type', 'sqlite').lower()
    conn_str = body.get('connection_string', '')
    query    = body.get('query', '')

    if not query:
        return jsonify({'success': False, 'error': 'query is required'}), 400

    try:
        if db_type == 'sqlite':
            conn = sqlite3.connect(conn_str or ':memory:')
            df   = pd.read_sql_query(query, conn)
            conn.close()
        elif db_type == 'postgres':
            if not POSTGRES_AVAILABLE:
                return jsonify({'success': False, 'error': 'psycopg2 not installed'}), 500
            conn = psycopg2.connect(conn_str)
            df   = pd.read_sql_query(query, conn)
            conn.close()
        elif db_type == 'mysql':
            if not MYSQL_AVAILABLE:
                return jsonify({'success': False, 'error': 'pymysql not installed'}), 500
            conn = pymysql.connect(**_parse_mysql(conn_str))
            df   = pd.read_sql_query(query, conn)
            conn.close()
        else:
            return jsonify({'success': False, 'error': f'Unsupported db type: {db_type}'}), 400

        entry = dataframe_to_source(df, f"{db_type}:{query[:40]}...", 'database')
        return jsonify({
            'success':      True,
            'source_id':    entry['id'],
            'record_count': entry['record_count'],
            'schema':       entry['schema'],
            'data':         entry['data'][:10],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Database error: {e}'}), 500


def _parse_mysql(conn_str: str) -> dict:
    """Very small mysql://user:pass@host:port/db parser."""
    from urllib.parse import urlparse
    u = urlparse(conn_str)
    return {'host': u.hostname, 'port': u.port or 3306,
            'user': u.username, 'password': u.password,
            'database': u.path.lstrip('/')}


# ── Analyze endpoint ──────────────────────────────────────────────────────────

@app.route('/api/v1/analyze', methods=['POST', 'OPTIONS'])
def analyze():
    if request.method == 'OPTIONS':
        return '', 204
    user, err, code = verify_api_key()
    if err:
        return err, code

    body    = request.get_json() or {}
    message = body.get('message', '').strip()
    src_id  = body.get('data_source_id')

    if not message:
        return jsonify({'success': False, 'error': 'message is required'}), 400

    status = check_groq_status()
    if not status['ready']:
        return jsonify({'success': False, 'error': status.get('error', 'Groq not ready'),
                        'insight': 'Check your GROQ_API_KEY in .env'}), 503

    if src_id:
        source = get_active_source(src_id)
        data_text = data_to_text(source) if source else "No data loaded."
    else:
        source = None
        data_text = get_all_sources_text()

    # Check response cache
    ckey   = _cache_key(message, source['id'] if source else None)
    cached = _get_cached(ckey)
    if cached:
        return jsonify({'success': True, 'insight': cached, 'cached': True,
                        'source_id': source['id'] if source else None,
                        'timestamp': datetime.now().isoformat()})



    try:
        # 1. Prepare Pandas environment
        if source:
            sources_to_use = [source]
        else:
            sources_to_use = list(DATA_SOURCES.values())
            
        dfs = {s['name']: s['df'] for s in sources_to_use if 'df' in s}
        
        schema_info = []
        for s in sources_to_use:
            schema_info.append(f"Table name: {s['name']}\nColumns: {list(s['schema'].keys())}")
        if not schema_info:
            schema_text = "No data sources are currently loaded."
        else:
            schema_text = "\n\n".join(schema_info)

        # 2. Ask Groq to write Python code or converse
        code_prompt = f"""You are an elite Data Analyst AI. 
We have the following pandas DataFrames loaded into variables:
{schema_text}

User Input: {message}

Instructions:
1. If the user is asking about the data, write a Python script using pandas to find the answer. Output ONLY a ```python ... ``` code block. Use `print()` to output the exact result. The DataFrames are loaded as variables matching their exact Table names (e.g. `VendorMaster`).
2. IMPORTANT: If 'schema_text' says 'No data sources are currently loaded.' AND the user is asking to analyze data, DO NOT write a Python script. Instead, inform them they need to connect a database or upload a file.
3. IMPORTANT: When searching or filtering text, ALWAYS use case-insensitive substring matching (e.g. `df[df['Column'].str.contains('term', case=False, na=False)]`). Do not use exact `==` matches for text.
4. CRITICAL: Never use `.values[0]`, `.iloc[0]`, or access indexes directly without checking if the DataFrame is empty. If a filter returns no rows, accessing `[0]` will crash the program with an "out of bounds" error. Simply print the dataframe or series directly (e.g. `print(df['Col'].mode())`).
5. IMPORTANT: If the user says hello, makes a conversational comment, or asks a general question unrelated to the data, ALWAYS respond naturally, greet them friendly, and answer their general question directly, even if no data is loaded! DO NOT write python code for this."""

        code_resp = groq_prompt(code_prompt, params={'temperature': 0.1, 'max_tokens': 1000})
        is_code = '```python' in code_resp.lower()
        
        if not is_code:
            # Conversational path
            insight = code_resp.strip()
            _set_cached(ckey, insight)
            return jsonify({
                'success':   True,
                'insight':   insight,
                'cached':    False,
                'source_id': source['id'] if source else None,
                'timestamp': datetime.now().isoformat(),
                'usage':     {'current': 1, 'limit': user['limit'], 'remaining': user['limit'] - 1},
            })

        # Data query path
        code = extract_python_code(code_resp)
        
        # 3. Execute the code
        exec_result = execute_pandas_code(dfs, code)
        print(f"\n[DEBUG] Generated Code:\n{code}\n[DEBUG] Exec Result:\n{exec_result}\n")
        
        # 4. Formulate the final answer
        final_prompt = f"""You are a Data Analyst assisting a user.
User Question: {message}

We executed an internal python script on the database to get the exact answer. The output was:
---
{exec_result}
---

Provide a natural, clear, and descriptive answer to the user based on this output. If it's an error, politely explain that the data couldn't be processed."""

        insight = groq_prompt(final_prompt, params=GROQ_PARAMS_FAST).strip()
        _set_cached(ckey, insight)
        return jsonify({
            'success':   True,
            'insight':   insight,
            'cached':    False,
            'source_id': source['id'] if source else None,
            'timestamp': datetime.now().isoformat(),
            'usage':     {'current': 1, 'limit': user['limit'], 'remaining': user['limit'] - 1},
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e),
                        'insight': f'Error: {e}'}), 500


@app.route('/api/v1/analyze/stream', methods=['POST', 'OPTIONS'])
def analyze_stream():
    """Streaming SSE endpoint — returns tokens as they arrive for instant perceived response."""
    if request.method == 'OPTIONS':
        return '', 204
    user, err, code = verify_api_key()
    if err:
        return err, code

    body    = request.get_json() or {}
    message = body.get('message', '').strip()
    src_id  = body.get('data_source_id')

    if not message:
        return jsonify({'success': False, 'error': 'message is required'}), 400

    status = check_groq_status()
    if not status['ready']:
        def err_stream():
            yield f"data: {json.dumps({'error': status.get('error','Groq not ready'), 'done': True})}\n\n"
        return Response(err_stream(), mimetype='text/event-stream')

    if src_id:
        source = get_active_source(src_id)
        data_text = data_to_text(source) if source else "No data loaded."
    else:
        source = None
        data_text = get_all_sources_text()

    # Serve from cache immediately if available
    ckey   = _cache_key(message, source['id'] if source else None)
    cached = _get_cached(ckey)
    if cached:
        def cached_stream():
            yield f"data: {json.dumps({'token': cached, 'done': False})}\n\n"
            yield f"data: {json.dumps({'done': True, 'cached': True})}\n\n"
        return Response(stream_with_context(cached_stream()), mimetype='text/event-stream')

    def generate():
        try:
            # 1. Prepare Pandas environment
            if source:
                sources_to_use = [source]
            else:
                sources_to_use = list(DATA_SOURCES.values())
                
            dfs = {s['name']: s['df'] for s in sources_to_use if 'df' in s}
            
            schema_info = []
            for s in sources_to_use:
                schema_info.append(f"Table name: {s['name']}\\nColumns: {list(s['schema'].keys())}")
            if not schema_info:
                schema_text = "No data sources are currently loaded."
            else:
                schema_text = "\\n\\n".join(schema_info)

            # 2. Ask Groq to write Python code or converse
            code_prompt = f"""You are an elite Data Analyst AI. 
We have the following pandas DataFrames loaded into variables:
{schema_text}

User Input: {message}

Instructions:
1. If the user is asking about the data, write a Python script using pandas to find the answer. Output ONLY a ```python ... ``` code block. Use `print()` to output the exact result. The DataFrames are loaded as variables matching their exact Table names (e.g. `VendorMaster`).
2. IMPORTANT: If 'schema_text' says 'No data sources are currently loaded.' AND the user is asking to analyze data, DO NOT write a Python script. Instead, inform them they need to connect a database or upload a file.
3. IMPORTANT: When searching or filtering text, ALWAYS use case-insensitive substring matching (e.g. `df[df['Column'].str.contains('term', case=False, na=False)]`). Do not use exact `==` matches for text.
4. CRITICAL: Never use `.values[0]`, `.iloc[0]`, or access indexes directly without checking if the DataFrame is empty. If a filter returns no rows, accessing `[0]` will crash the program with an "out of bounds" error. Simply print the dataframe or series directly (e.g. `print(df['Col'].mode())`).
5. IMPORTANT: If the user says hello, makes a conversational comment, or asks a general question unrelated to the data, ALWAYS respond naturally, greet them friendly, and answer their general question directly, even if no data is loaded! DO NOT write python code for this."""

            code_resp = groq_prompt(code_prompt, params={'temperature': 0.1, 'max_tokens': 1000})
            is_code = '```python' in code_resp.lower()
            
            if not is_code:
                # Conversational path
                conv_msg = {'token': code_resp.strip(), 'done': False}
                yield f"data: {json.dumps(conv_msg)}\n\n"
                _set_cached(ckey, code_resp.strip())
                done_msg = {'done': True, 'cached': False}
                yield f"data: {json.dumps(done_msg)}\n\n"
                return

            # Data query path
            code = extract_python_code(code_resp)
            
            query_msg = {'token': '⚙️ Querying data on all rows...\n\n', 'done': False}
            yield f"data: {json.dumps(query_msg)}\n\n"
            
            # 3. Execute the code
            exec_result = execute_pandas_code(dfs, code)
            print(f"\n[DEBUG] Generated Code:\n{code}\n[DEBUG] Exec Result:\n{exec_result}\n")
            
            # 4. Formulate the final answer stream
            final_prompt = f"""You are a Data Analyst assisting a user.
User Question: {message}

We executed an internal python script on the database to get the exact answer. The output was:
---
{exec_result}
---

Provide a natural, clear, and descriptive answer to the user based on this output. If it's an error, politely explain that the data couldn't be processed."""

            full = []
            for token in groq_stream(final_prompt, params=GROQ_PARAMS_FAST):
                full.append(token)
                token_msg = {'token': token, 'done': False}
                yield f"data: {json.dumps(token_msg)}\n\n"
                
            combined = ''.join(full).strip()
            # Prefix the original thought process to the cached version so it looks consistent on reload
            _set_cached(ckey, f"🧠 Thought Process: Wrote query -> Executed\n\n{combined}")
            final_msg = {'done': True, 'cached': False}
            yield f"data: {json.dumps(final_msg)}\n\n"
            
        except Exception as e:
            err_msg = {'error': str(e), 'done': True}
            yield f"data: {json.dumps(err_msg)}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ── Dashboard endpoint ────────────────────────────────────────────────────────

@app.route('/api/v1/dashboard/generate', methods=['POST', 'OPTIONS'])
def generate_dashboard():
    if request.method == 'OPTIONS':
        return '', 204
    user, err, code = verify_api_key()
    if err:
        return err, code

    body    = request.get_json() or {}
    message = body.get('message', 'Create a dashboard').strip()
    src_id  = body.get('data_source_id')
    mode    = body.get('type', 'inbuilt')   # 'inbuilt' | 'download'

    status = check_groq_status()
    if not status['ready']:
        return jsonify({'success': False, 'error': status.get('error', 'Groq not ready')}), 503

    source = get_active_source(src_id)
    if not source:
        return jsonify({'success': False, 'error': 'No data source available. Upload a file or connect a database first.'}), 400

    data_text = data_to_text(source)

    # STEP 1: Plan the dashboard
    planner_prompt = f"""You are an expert data analyst and UX designer. Given the data sample and user request, create a detailed blueprint for a high-end Chart.js dashboard.
If the data does not contain numerical values suitable for charting or if the user request is completely unrelated to the data, output EXACTLY AND ONLY:
WARNING: [explain why the dashboard cannot be created]

Otherwise, output a detailed blueprint specifying:
1. Dashboard Title: A catchy, professional title.
2. KPI Cards: Define 3-4 specific KPI metrics to calculate from the data (e.g., Total Sales, Average Score). Specify the exact math logic to compute them.
3. Charts: Define exactly what charts to create. Specify the exact column names to use for labels (X-axis) and data (Y-axis).
4. Styling: Define a dark, modern, premium aesthetic (e.g. background #0f172a, cards #1e293b, vivid accent colors like #6366f1 or #ec4899, soft shadows, rounded corners).

Data sample:
{data_text}

User request: {message}
Blueprint:"""

    try:
        plan = groq_prompt(planner_prompt, params=GROQ_PARAMS_FAST).strip()
        
        # Check if the model returned a warning
        if plan.upper().startswith("WARNING:"):
            warning_msg = plan[8:].strip()
            return jsonify({'success': False, 'error': warning_msg})

        # STEP 2: Generate the HTML using the plan
        generator_prompt = f"""You are a senior frontend developer. Generate a COMPLETE, standalone HTML page containing a premium Chart.js dashboard implementing this blueprint:

Blueprint:
{plan}

Data Schema Sample:
{data_text}

CRITICAL RULES FOR JAVASCRIPT & DATA:
1. DO NOT hardcode data values. The full dataset is already injected into the page via a global variable called `window.dashboardData` (an array of JSON objects).
2. Write JavaScript to iterate over `window.dashboardData` to dynamically calculate the KPI values and extract the arrays needed for the charts.
3. Ensure you handle data types properly (e.g., parse strings to numbers if needed).

CRITICAL RULES FOR HTML & CSS:
1. Output ONLY valid HTML (no markdown fences, no explanation outside the HTML).
2. Use Chart.js via CDN: https://cdn.jsdelivr.net/npm/chart.js
3. Use internal <style> blocks. Do not link external stylesheets.
4. Implement a stunning, premium dark mode aesthetic using CSS Grid/Flexbox. Use glassmorphism or sleek solid panels, smooth hover effects, and modern typography (sans-serif).
HTML:"""

        raw_html = groq_prompt(generator_prompt, params=GROQ_PARAMS_DASH).strip()
        
        # Strip any accidental markdown fences
        if raw_html.startswith("```"):
            raw_html = "\n".join(raw_html.split("\n")[1:])
            if raw_html.startswith("html"):
                raw_html = raw_html[4:]
        if raw_html.endswith("```"):
            raw_html = "\n".join(raw_html.split("\n")[:-1])
        raw_html = raw_html.strip()

        # Inject the full JSON data so the dashboard works instantly
        full_json = json.dumps(source.get('data', []))
        data_script = f"\n<script>\n// Auto-injected dataset\nwindow.dashboardData = {full_json};\n</script>\n"
        
        # Inject right after <head> if it exists, otherwise prepend
        if "<head>" in raw_html.lower():
            raw_html = raw_html.replace("<head>", f"<head>{data_script}", 1)
        elif "<body>" in raw_html.lower():
            raw_html = raw_html.replace("<body>", f"<body>{data_script}", 1)
        else:
            raw_html = data_script + raw_html

        # Always save to a file so the user can download it natively
        fname   = f"dashboard_{uuid.uuid4().hex[:8]}.html"
        fpath   = os.path.join(DOWNLOAD_DIR, fname)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(raw_html)
        
        download_url = f'/downloads/{fname}'

        if mode == 'download':
            return jsonify({
                'success':      True,
                'download_url': download_url,
                'filename':     fname,
            })
        else:
            return jsonify({'success': True, 'html': raw_html, 'download_url': download_url})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/downloads/<path:filename>', methods=['GET'])
def serve_download(filename):
    return send_from_directory(os.path.abspath(DOWNLOAD_DIR), filename)


# ── Tracking & error handlers ─────────────────────────────────────────────────

@app.route('/api/v1/track', methods=['POST', 'OPTIONS'])
def track_usage():
    if request.method == 'OPTIONS':
        return '', 204
    user, err, code = verify_api_key()
    if err:
        return err, code
    data  = request.get_json() or {}
    event = data.get('event', 'unknown')
    print(f"📊 Event: {event} | User: {user['user']}")
    return jsonify({'success': True})


@app.errorhandler(404)
def not_found(e):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def internal_error(e):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500


SQL_ERROR = None
PG_ERROR = None

def preload_databases():
    global SQL_ERROR, PG_ERROR
    # --- SQL SERVER LOGIC ---
    if PANDAS_AVAILABLE and PYMSSQL_AVAILABLE:
        mssql_server   = os.getenv('MSSQL_SERVER', '')
        mssql_database = os.getenv('MSSQL_DATABASE', '')
        mssql_user     = os.getenv('MSSQL_USER', '')
        mssql_password = os.getenv('MSSQL_PASSWORD', '')
        mssql_schema   = os.getenv('MSSQL_SCHEMA', mssql_user)

        if mssql_server and mssql_user:
            try:
                conn = pymssql.connect(
                    server=mssql_server,
                    user=mssql_user,
                    password=mssql_password,
                    database=mssql_database
                )

                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT TABLE_NAME FROM {mssql_database}.INFORMATION_SCHEMA.TABLES "
                    f"WHERE TABLE_SCHEMA = '{mssql_schema}' AND TABLE_TYPE = 'BASE TABLE'"
                )
                tables = [row[0] for row in cursor.fetchall()]

                total_loaded = 0
                for table in tables:
                    try:
                        query = f"SELECT * FROM {mssql_database}.{mssql_schema}.{table}"
                        df_sql = pd.read_sql_query(query, conn)
                        dataframe_to_source(df_sql, table, 'database')
                        total_loaded += 1
                        print(f"🗄️  Pre-loaded SQL Server table {table} with {len(df_sql)} rows.")
                    except Exception as table_err:
                        print(f"⚠️  Could not load table {table}: {table_err}")

                conn.close()
                print(f"✅ Successfully loaded {total_loaded} tables from SQL Server [{mssql_schema}].")
            except Exception as e:
                SQL_ERROR = str(e)
                print(f"⚠️  Could not connect to SQL Server: {e}")
        else:
            SQL_ERROR = "Environment variables (MSSQL_SERVER) not found"
            print("ℹ️  SQL Server: skipped (MSSQL_SERVER / MSSQL_USER not set in .env)")

    # --- POSTGRES LOGIC ---
    if PANDAS_AVAILABLE and POSTGRES_AVAILABLE:
        pg_host     = os.getenv('PG_HOST', '')
        pg_port     = os.getenv('PG_PORT', '5432')
        pg_dbname   = os.getenv('PG_DBNAME', 'postgres')
        pg_user     = os.getenv('PG_USER', 'postgres')
        pg_password = os.getenv('PG_PASSWORD', '')
        pg_schema   = os.getenv('PG_SCHEMA', 'public')

        if pg_host and pg_password:
            try:
                conn = psycopg2.connect(
                    host=pg_host,
                    port=pg_port,
                    dbname=pg_dbname,
                    user=pg_user,
                    password=pg_password,
                    sslmode='require'
                )

                cursor = conn.cursor()
                cursor.execute(f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{pg_schema}'")
                tables = [row[0] for row in cursor.fetchall()]

                total_loaded = 0
                for table in tables:
                    try:
                        query = f"SELECT * FROM {pg_schema}.{table}"
                        df_pg = pd.read_sql_query(query, conn)
                        dataframe_to_source(df_pg, table, 'database')
                        total_loaded += 1
                        print(f"🐘  Pre-loaded Postgres table {table} with {len(df_pg)} rows.")
                    except Exception as table_err:
                        print(f"⚠️  Could not load Postgres table {table}: {table_err}")

                conn.close()
                print(f"✅ Successfully loaded {total_loaded} Postgres tables from {pg_schema}.")
            except Exception as e:
                PG_ERROR = str(e)
                print(f"⚠️  Could not connect to Postgres Database: {e}")
        else:
            PG_ERROR = "Environment variables (PG_HOST / PG_PASSWORD) not found"
            print("ℹ️  Postgres: skipped (PG_HOST / PG_PASSWORD not set in .env)")

# Load databases globally so gunicorn workers execute this
preload_databases()

# ── Startup ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port   = int(os.getenv('PORT', 5000))
    status = check_groq_status()

    print("\n" + "=" * 60)
    print("🤖  NexBot AI — Data Chatbot API (Groq)")
    print("=" * 60)
    print(f"📍  Port        : {port}")
    print(f"🧠  Model       : {GROQ_MODEL}")
    print(f"🔑  Groq Key    : {'✅ set' if GROQ_API_KEY else '❌ missing — add GROQ_API_KEY to .env'}")
    print(f"📦  pandas      : {'✅' if PANDAS_AVAILABLE else '❌ (install pandas)'}")
    print(f"🔐  bcrypt      : {'✅' if BCRYPT_AVAILABLE else '⚠️  optional (password hashing)'}")
    print(f"🐘  psycopg2    : {'✅' if POSTGRES_AVAILABLE else '⚠️  optional'}")
    print(f"🐬  pymysql     : {'✅' if MYSQL_AVAILABLE else '⚠️  optional'}")
    print(f"🗄️  pymssql     : {'✅' if PYMSSQL_AVAILABLE else '⚠️  optional (SQL Server)'}")
    print(f"{'✅  Groq ready — no warm-up needed!' if status['ready'] else '❌  ' + status.get('error','')}")
    print("─" * 60)
    print(f"🔌  Plugin Reg  : POST /api/v1/register (password-protected)")
    print(f"🗃️  License DB  : {LICENSE_DB_PATH}")
    print(f"📜  Plugin JS   : GET /plugin/chatbot-plugin.js")
    print(f"👤  Admin Keys  : GET /api/v1/admin/keys (X-Admin-Password header)")
    print("=" * 60 + "\n")

    app.run(host='0.0.0.0', port=port, debug=True)
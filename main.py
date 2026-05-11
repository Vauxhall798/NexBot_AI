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

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

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
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
UPLOAD_DIR   = os.getenv('UPLOAD_DIR', 'uploads')
DOWNLOAD_DIR = os.getenv('DOWNLOAD_DIR', 'downloads')
CACHE_TTL    = int(os.getenv('DATA_CACHE_TTL', 300))
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
GROQ_MODEL   = 'llama-3.1-8b-instant'  # Using the extremely fast free model for insights

# ── Plugin Registration ──────────────────────────────────────────────────────
# Master password that users must supply to register as a plugin consumer.
# Set this in your .env file. Anyone who knows this password can self-register.
ADMIN_PASSWORD   = os.getenv('NEXBOT_ADMIN_PASSWORD', 'changeme_super_secret')
LICENSE_DB_PATH  = os.getenv('LICENSE_DB_PATH', 'data/licenses.db')

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


def gemini_prompt(prompt: str, params: dict = None) -> str:
    """Non-streaming Gemini API call using massive context limits."""
    if not GEMINI_AVAILABLE:
        raise Exception("google-generativeai package not installed.")
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY not configured.")
    genai.configure(api_key=GEMINI_API_KEY)
    
    # Set high output limit to prevent dashboards from being cut off
    config = genai.types.GenerationConfig(max_output_tokens=8192, temperature=0.1)
    
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt, generation_config=config)
        return response.text or ''
    except Exception as e:
        error_str = str(e).lower()
        if '429' in error_str or 'quota' in error_str or 'rate' in error_str:
            print(f"[API FALLBACK] 429 Hit on {GEMINI_MODEL}. Falling back to gemini-2.0-flash...")
            try:
                fallback_model = genai.GenerativeModel('gemini-2.0-flash')
                response = fallback_model.generate_content(prompt, generation_config=config)
                return response.text or ''
            except Exception as fallback_e:
                # 3RD TIER FALLBACK: Groq (using Llama 3.1 8B which has high free limits)
                groq_key = os.getenv('GROQ_API_KEY')
                if groq_key:
                    print("[API FALLBACK] Gemini exhausted. Falling back to Groq Llama-3.1-8b...")
                    try:
                        from groq import Groq
                        client = Groq(api_key=groq_key)
                        chat_completion = client.chat.completions.create(
                            messages=[{"role": "user", "content": prompt}],
                            model="llama-3.1-8b-instant",
                        )
                        return chat_completion.choices[0].message.content or ''
                    except Exception as groq_e:
                        raise Exception(f"All AI engines (Gemini & Groq) exhausted: {groq_e}")
                raise Exception(f"Gemini API (and Fallback) error: {fallback_e}")
        raise Exception(f"Gemini API error: {e}")

def gemini_stream(prompt: str, params: dict = None):
    """Generator that yields text tokens from Gemini streaming API with 3-tier fallback."""
    if not GEMINI_AVAILABLE:
        raise Exception("google-generativeai package not installed.")
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY not configured.")
    genai.configure(api_key=GEMINI_API_KEY)
    
    config = genai.types.GenerationConfig(max_output_tokens=8192, temperature=0.1)
    
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content(prompt, stream=True, generation_config=config)
        for chunk in response:
            if chunk.text:
                yield chunk.text
    except Exception as e:
        error_str = str(e).lower()
        if '429' in error_str or 'quota' in error_str or 'rate' in error_str:
            print(f"[API FALLBACK] 429 Hit on {GEMINI_MODEL}. Falling back to gemini-2.0-flash...")
            try:
                fallback_model = genai.GenerativeModel('gemini-2.0-flash')
                response = fallback_model.generate_content(prompt, stream=True, generation_config=config)
                for chunk in response:
                    if chunk.text:
                        yield chunk.text
            except Exception as fallback_e:
                # 3RD TIER FALLBACK: Groq
                groq_key = os.getenv('GROQ_API_KEY')
                if groq_key:
                    print("[API FALLBACK] Gemini exhausted. Falling back to Groq stream...")
                    try:
                        from groq import Groq
                        client = Groq(api_key=groq_key)
                        completion = client.chat.completions.create(
                            model="llama-3.1-8b-instant",
                            messages=[{"role": "user", "content": prompt}],
                            stream=True,
                        )
                        for chunk in completion:
                            if chunk.choices[0].delta.content:
                                yield chunk.choices[0].delta.content
                        return
                    except Exception as groq_e:
                        yield f"\n[All AI engines exhausted: {groq_e}]"
                else:
                    yield f"\n[Gemini Fallback Error: {fallback_e}]"
        else:
            yield f"\n[Gemini API Error: {e}]"

def check_system_status() -> dict:
    """Verify the system state, models, and data connectivity."""
    status = {
        'ready': True,
        'model': GEMINI_MODEL,
        'data_sources_loaded': len(DATA_SOURCES),
        'tables': [s['name'] for s in DATA_SOURCES.values()],
        'postgres_error': globals().get('PG_ERROR', None)
    }
    if not GEMINI_API_KEY:
        status['ready'] = False
        status['error'] = 'GEMINI_API_KEY not set'
    
    status['groq_ready'] = GROQ_AVAILABLE and bool(GROQ_API_KEY)
    return status

def groq_prompt(prompt: str) -> str:
    """Non-streaming Groq call specifically for insights."""
    if not GROQ_AVAILABLE: raise Exception("Groq package not installed.")
    if not GROQ_API_KEY: raise Exception("GROQ_API_KEY not configured.")
    client = Groq(api_key=GROQ_API_KEY)
    try:
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=GROQ_MODEL,
        )
        return completion.choices[0].message.content or ''
    except Exception as e:
        raise Exception(f"Groq API error: {e}")

def groq_stream(prompt: str):
    """Streaming Groq call specifically for insights."""
    if not GROQ_AVAILABLE: raise Exception("Groq package not installed.")
    if not GROQ_API_KEY: raise Exception("GROQ_API_KEY not configured.")
    client = Groq(api_key=GROQ_API_KEY)
    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        for chunk in completion:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        yield f"\n[Groq API Error: {e}]"


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
    # Ensure full data is available for accurate frontend dashboard aggregations
    data = df.fillna('').to_dict(orient='records')
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
    
    # Hard cap length to avoid 400 errors from Gemini API
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
    
    # If using Gemini, unlock massive context. If Groq, constrain to 4k characters.
    limit = 500000 if GEMINI_API_KEY else 4000
    if len(combined) > limit:
        combined = combined[:limit] + "\n...[truncated due to strict token limits]..."
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
        result = output.getvalue().strip()
        if not result:
            return "Code executed successfully but produced no output."
        
        # Protect against massive outputs triggering Gemini Rate Limit
        if len(result) > 4000:
            result = result[:4000] + "\n...[Output truncated due to excessive length. The data was too large to print fully.]..."
            
        return result
    except Exception as e:
        return f"Error executing code: {e}"

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'model': GEMINI_MODEL,
        'data_sources': len(DATA_SOURCES),
        'sql_status': SQL_ERROR,
        'pg_status': PG_ERROR,
        'service': 'AI Data Chatbot API (Gemini)',
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

@app.route('/api/v1/status', methods=['GET', 'OPTIONS'])
def get_system_status():
    return jsonify(check_system_status())

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

    status = check_system_status()
    if not status['ready']:
        return jsonify({'success': False, 'error': status.get('error', 'Gemini not ready'),
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

        # 2. Ask Gemini to write Python code or converse
        code_prompt = f"""You are "NexBot", an elite Data Science & Analytics AI.
We have the following pandas DataFrames loaded:
{schema_text}

User Input: {message}

Instructions:
1. ANALYSIS: If the user asks for insights, summaries, or questions about the data, ALWAYS write a Python script using pandas. Output ONLY a ```python ... ``` code block.
"""
        # Data query path
        code_resp = groq_prompt(code_prompt)
        code = extract_python_code(code_resp)
        exec_result = execute_pandas_code(dfs, code)
        
        final_prompt = f"User Question: {message}\nOutput: {exec_result}\nAnswer as NexBot."
        insight = groq_prompt(final_prompt).strip()
        
        _set_cached(ckey, insight)
        return jsonify({
            'success': True, 'insight': insight, 'cached': False,
            'source_id': source['id'] if source else None,
            'timestamp': datetime.now().isoformat(),
            'usage': {'current': 1, 'limit': user['limit'], 'remaining': user['limit'] - 1},
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/v1/analyze/stream', methods=['POST', 'OPTIONS'])
def analyze_stream():
    """Streaming SSE endpoint powered by Groq."""
    if request.method == 'OPTIONS': return '', 204
    user, err, code_err = verify_api_key()
    if err: return err, code_err

    body = request.get_json() or {}
    message = body.get('message', '').strip()
    src_id = body.get('data_source_id')
    if not message: return jsonify({'success': False, 'error': 'message required'}), 400

    status = check_system_status()
    if not status['groq_ready']:
        def err_stream(): yield "data: " + json.dumps({'error': 'Groq not ready', 'done': True}) + "\n\n"
        return Response(err_stream(), mimetype='text/event-stream')

    source = get_active_source(src_id) if src_id else None
    ckey = _cache_key(message, source['id'] if source else None)
    cached = _get_cached(ckey)
    if cached:
        def cached_stream():
            yield "data: " + json.dumps({'token': cached, 'done': False}) + "\n\n"
            yield "data: " + json.dumps({'done': True, 'cached': True}) + "\n\n"
        return Response(stream_with_context(cached_stream()), mimetype='text/event-stream')

    def generate():
        try:
            dfs = {s['name']: s['df'] for s in (([source] if source else list(DATA_SOURCES.values()))) if 'df' in s}
            schema_text = "\n".join([f"Table: {s['name']} (Cols: {list(s['schema'].keys())})" for s in (([source] if source else list(DATA_SOURCES.values())))])
            
            code_prompt = f"User: {message}\nData: {schema_text}\nIf data question, output ONLY ```python ... ``` using pandas. Else converse."
            code_resp = groq_prompt(code_prompt)
            
            if '```python' not in code_resp.lower():
                yield "data: " + json.dumps({'token': code_resp.strip(), 'done': False}) + "\n\n"
                _set_cached(ckey, code_resp.strip())
                yield "data: " + json.dumps({'done': True}) + "\n\n"
                return

            code = extract_python_code(code_resp)
            yield "data: " + json.dumps({'token': '⚙️ Analyzing...\n\n', 'done': False}) + "\n\n"
            exec_res = execute_pandas_code(dfs, code)
            
            final_p = f"User: {message}\nResult: {exec_res}\nExplain as NexBot."
            full_ans = []
            for token in groq_stream(final_p):
                full_ans.append(token)
                yield "data: " + json.dumps({'token': token, 'done': False}) + "\n\n"
            _set_cached(ckey, "".join(full_ans))
            yield "data: " + json.dumps({'done': True}) + "\n\n"
        except Exception as e:
            yield "data: " + json.dumps({'error': str(e), 'done': True}) + "\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

# ── Dashboard endpoint ────────────────────────────────────────────────────────

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

    status = check_system_status()
    if not status['ready']:
        return jsonify({'success': False, 'error': status.get('error', 'Gemini not ready')}), 503

    if src_id:
        active = get_active_source(src_id)
        if not active:
            return jsonify({'success': False, 'error': 'No data source available. Upload a file or connect a database first.'}), 400
        sources_to_use = [active]
    else:
        sources_to_use = list(DATA_SOURCES.values())
        if not sources_to_use:
            return jsonify({'success': False, 'error': 'No data source available. Upload a file or connect a database first.'}), 400

    if len(sources_to_use) == 1:
        data_text = data_to_text(sources_to_use[0])
    else:
        data_text = get_all_sources_text()

    # STEP 1: Plan the dashboard
    planner_prompt = f"""You are a Principal Data Scientist and Executive Dashboard Architect. Your primary goal is to perform deep, statistical data analysis and uncover hidden business trends. Given the data sample and user request, create a highly analytical blueprint for a premium Chart.js dashboard.

If the data does not contain numerical values suitable for charting OR the user request is completely unrelated to the data, output EXACTLY AND ONLY:
WARNING: [explain why the dashboard cannot be created]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHART TYPE CATALOGUE — pick the BEST type(s) from below based on the data and user intent:

1. COMPARISON & RANKING
   • bar          → Horizontal bars: compare categorical values side-by-side
   • column       → Vertical bars: same as bar but vertical
   • radar        → Web/spider chart: compare multiple variables per category
   • dotplot      → Dot plot: minimal bar alternative, great for rankings

2. TRENDS OVER TIME (Time-Series)
   • line         → Line chart: trends/fluctuations over continuous time
   • area         → Area chart: like line but filled — shows volume/magnitude
   • candlestick  → Candlestick: financial OHLC price movements

3. COMPOSITION (Part-to-Whole)
   • pie          → Pie chart: proportions of a whole
   • doughnut     → Doughnut: pie with hollow center for labeling
   • treemap      → Treemap: nested rectangles for hierarchical proportions
   • stackedbar   → Stacked bar: cumulative part-of-whole across categories
   • stackedcolumn→ Stacked column: vertical variant of stacked bar

4. CORRELATION & DISTRIBUTION
   • scatter      → Scatter plot: relationship between 2 numeric variables
   • bubble       → Bubble chart: 3-variable scatter (x, y, bubble size)
   • histogram    → Histogram: frequency distribution of a continuous variable
   • heatmap      → Heatmap: color-coded matrix for pattern detection
   • boxplot      → Box & whisker: distribution, median, outliers

5. FLOW & PROCESS
   • funnel       → Funnel: values through process stages (e.g. conversion)
   • sankey       → Sankey: flow diagram with proportional arrow widths
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Output a detailed blueprint with:
1. Dashboard Title: A catchy, professional title.
2. KPI Cards: 3-4 specific KPI metrics with exact calculation logic (sum, avg, count, max, min).
3. Charts: Strictly limit the dashboard to a MAXIMUM of 4 premium, high-impact charts. For each chart specify:
   - chart_type: one of the keys above (e.g. "bar", "line", "heatmap")
   - title: chart title
   - x_column: exact column name for labels/x-axis
   - y_column: exact column name(s) for values/y-axis (comma-separated if multiple)
   - description: brief note on what insight this reveals
4. Styling: Modern light premium aesthetic — background #f8fafc, cards #ffffff with subtle shadows, accent colors from [#6366f1, #10b981, #f43f5e], rounded corners. No sidebar.
5. Intelligent Features: Plan a layout with KPI trend badges, an Executive Summary text block, and mention the interactive drill-down capability.
6. Chart Limitations (CRITICAL): Do NOT generate a chart for every single table. Identify ONLY the top 3 or 4 most important business insights across the entire database and chart those. Less is more.

Data sample:
{data_text}

User request: {message}
Blueprint:"""

    try:
        if GEMINI_API_KEY and GEMINI_AVAILABLE:
            plan = gemini_prompt(planner_prompt).strip()
        else:
            plan = gemini_prompt(planner_prompt).strip()
            plan = re.sub(r'<think>.*?</think>', '', plan, flags=re.DOTALL).strip()

        # Check if the model returned a warning
        if plan.upper().startswith("WARNING:"):
            warning_msg = plan[8:].strip()
            return jsonify({'success': False, 'error': warning_msg})

        # STEP 2: Generate the HTML using the plan
        # NOTE: Plain string concatenation used (not f-string) to avoid Python
        # parsing conflicts with JS syntax: [...arr], =>, ??, && inside f-strings.
        _SORT_HELPER = (
            "   const MONTH_ORDER = {\n"
            "     jan:0, january:0, feb:1, february:1, mar:2, march:2,\n"
            "     apr:3, april:3, may:4, jun:5, june:5, jul:6, july:6,\n"
            "     aug:7, august:7, sep:8, sept:8, september:8,\n"
            "     oct:9, october:9, nov:10, november:10, dec:11, december:11\n"
            "   };\n"
            "   function sortByTime(arr, key) {\n"
            "     return arr.slice().sort(function(a, b) {\n"
            "       var av = String(a[key] != null ? a[key] : '').trim();\n"
            "       var bv = String(b[key] != null ? b[key] : '').trim();\n"
            "       var am = MONTH_ORDER[av.toLowerCase().slice(0,3)];\n"
            "       var bm = MONTH_ORDER[bv.toLowerCase().slice(0,3)];\n"
            "       if (am !== undefined && bm !== undefined) return am - bm;\n"
            "       var ad = new Date(av), bd = new Date(bv);\n"
            "       if (!isNaN(ad) && !isNaN(bd)) return ad - bd;\n"
            "       return parseFloat(av) - parseFloat(bv);\n"
            "     });\n"
            "   }\n"
            "   // Usage: var sorted = sortByTime(window.dashboardData['table_name'], 'month_col');\n"
            "   // labels = sorted.map(function(r){ return r.month_col; });\n"
            "   // values = sorted.map(function(r){ return parseFloat(r.val_col)||0; });\n"
        )

        generator_prompt = (
            "You are a senior frontend developer specialising in data visualisation. "
            "Generate a COMPLETE, self-contained HTML page that implements the following dashboard blueprint.\n\n"
            "Blueprint:\n" + plan + "\n\n"
            "Data Schema Sample (for column reference only — do NOT hardcode any values):\n" + data_text + "\n\n"
            "JAVASCRIPT & DATA RULES:\n"
            "1. The datasets are in `window.dashboardData`. Use EXACT table names from the schema below (case-sensitive). Example: `window.dashboardData['exact_table_name']`.\n"
            "2. Dynamically compute KPI values and chart arrays by iterating the arrays in `window.dashboardData`.\n"
            "3. Parse strings to numbers where needed: parseFloat(v) || 0.\n"
            "4. CRITICAL — SORT TIME-SERIES CHRONOLOGICALLY. You MUST copy and use this helper "
            "for EVERY chart that has a time/month/date axis — do NOT rely on the data's original order:\n\n"
            + _SORT_HELPER +
            "\nCHART LIBRARY RULES:\n"
            "- Always load Chart.js 4 first: https://cdn.jsdelivr.net/npm/chart.js\n"
            "- For TREEMAP: also load https://cdn.jsdelivr.net/npm/chartjs-chart-treemap@2\n"
            "- For BOXPLOT: also load https://cdn.jsdelivr.net/npm/@sgratzl/chartjs-chart-boxplot\n"
            "- For SANKEY: draw on Canvas using custom JavaScript (no plugin needed).\n"
            "- For HEATMAP: use CSS grid with inline background-color scaling by value intensity.\n"
            "- For FUNNEL: CSS trapezoid shapes with proportional widths and gradient fills.\n"
            "- For CANDLESTICK: draw OHLC rectangles on Canvas manually.\n"
            "- For DOTPLOT: Chart.js scatter with pointStyle circle and large radius.\n"
            "- Bar = Chart.js bar with indexAxis y. Column = bar vertical. Area = line with fill true.\n"
            "- Stacked bar/column: stacked true. Histogram: bin data manually then render as bar.\n"
            "- Radar, Pie, Doughnut, Scatter, Bubble, Line — native Chart.js types.\n\n"
            "EXECUTIVE UI/UX & CSS RULES:\n"
            "1. Output ONLY valid HTML — no markdown fences, no text outside the HTML.\n"
            "2. ONLY internal style blocks. Import Google Fonts Inter (wght 300;400;500;600;700;800).\n"
            "3. STUNNING VIBRANT LIGHT MODE: `body` MUST be `background: #f8fafc; color: #1e293b; font-family: 'Inter', sans-serif; padding: 40px; margin: 0; min-height: 100vh;` \n"
            "4. DASHBOARD HEADER: Make the main `h1` incredibly vibrant using a gradient: `background: linear-gradient(to right, #6366f1, #8b5cf6, #d946ef); -webkit-background-clip: text; color: transparent; font-weight: 800; font-size: 2.5rem;`\n"
            "5. CARDS: ALL cards (KPIs and Charts) MUST use `background: #ffffff; border: 1px solid #e2e8f0; border-radius: 24px; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.03); position: relative;` \n"
            "6. KPI GRID: `display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; margin-bottom: 40px;` \n"
            "7. MASSIVE CHART GRID: Charts MUST be large! Wrap chart cards in a container with `display: grid; grid-template-columns: repeat(auto-fit, minmax(500px, 1fr)); gap: 40px;`.\n"
            "8. CHART CANVAS HEIGHT: Ensure the `div` wrapping each `<canvas>` has `height: 450px; position: relative; margin-top: 20px;`.\n"
            "9. COLORS (CRITICAL): You MUST declare `const CHART_COLORS = ['#6366f1', '#10b981', '#f43f5e', '#f59e0b', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16'];` globally. \n"
            "10. EXPORT & DELETE (CRITICAL): \n"
            "    - Add an 'Export Dashboard (.html)' button to the top-right header.\n"
            "    - Add a small, elegant 'Remove' button in the top-right corner of each chart card (`position: absolute; top: 15px; right: 15px;`).\n"
            "    - Style the Remove button as a light grey circle that turns red on hover. \n"
            "11. Add a nicely styled `#data-table-container` div at the bottom (hidden by default) for raw data view.\n\n"
            "EXECUTIVE JAVASCRIPT LOGIC (CRITICAL):\n"
            "1. INSIGHTS: The 'Dynamic Executive Summary' MUST identify the highest performing category/product, note major trends, and provide a strategic recommendation. IMPORTANT: Use <b> tags for all key entities, product names, and high-impact numbers (e.g. <b>$734,378</b>) to make them stand out.\n"
            "2. FORMATTING: Use `Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })` to format large numbers (e.g. 1.8M instead of 1862300).\n"
            "3. DATES: Format timestamps beautifully using `new Date(val).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })`.\n"
            "4. CROSS-VALIDATION (CRITICAL): Add an `onClick` event to EVERY Chart.js instance. When a user clicks a bar, line point, or pie slice, extract the clicked label/category. Then, filter `window.dashboardData` to find all raw rows matching that category, and dynamically generate an HTML table inside `#data-table-container` showing the underlying raw data rows so the user can cross-validate the numbers. Scroll the user down to see the table.\n"
            "4. DATA LIMITS: If 'Top N', use `.sort((a,b) => b[valKey] - a[valKey]).slice(0, N)`. For Line/Bar charts, if the dataset has >30 rows, you MUST aggregate the data in JS (e.g. sum by month) or `.slice(-30)` the most recent points. Do NOT plot hundreds of points as it makes the chart unreadable.\n"
            "5. NO HTML CHARTS: ALL charts MUST be drawn using Chart.js `<canvas>`. NEVER draw charts using raw HTML `<div>` elements with dynamic heights, as they cause massive overflow bugs.\n"
            "6. CHART OPTIONS: Always pass `options: { responsive: true, maintainAspectRatio: false }` to Chart.js.\n"
            "7. KPI BADGES: Must contain actual text (e.g., '▲ 12.4%'). Style them with soft background pills. CRITICAL: NEVER output blue dots, placeholder character sparklines (like '....'), or any other junk symbols inside the cards.\n"
            "8. INTERACTIVE FEATURES: \n"
            "   - Implement `window.removeCard(btn)` function: `btn.closest('.card').remove();`.\n"
            "   - Implement `window.exportToHTML()` function: Create a Blob from `document.documentElement.outerHTML`, generate a URL, and trigger a download of 'NexBot_Dashboard.html'. \n"
            "HTML:"
        )

        if GEMINI_API_KEY and GEMINI_AVAILABLE:
            raw_html = gemini_prompt(generator_prompt).strip()
        else:
            raw_html = gemini_prompt(generator_prompt).strip()
            raw_html = re.sub(r'<think>.*?</think>', '', raw_html, flags=re.DOTALL).strip()
        
        # Strip any accidental markdown fences
        if raw_html.startswith("```"):
            raw_html = "\n".join(raw_html.split("\n")[1:])
            if raw_html.startswith("html"):
                raw_html = raw_html[4:]
        if raw_html.endswith("```"):
            raw_html = "\n".join(raw_html.split("\n")[:-1])
        raw_html = raw_html.strip()

        # Inject the full JSON data so the dashboard works instantly
        full_json_dict = {s['name']: s.get('data', []) for s in sources_to_use}
        full_json = json.dumps(full_json_dict, default=str)
        data_script = f"""
<script>
// Auto-injected datasets
window.dashboardData = {full_json};

// Resilient Global Chart.js Hook (waits for library to load)
(function() {{
    function registerVibrantHook() {{
        if (typeof Chart === 'undefined') {{
            setTimeout(registerVibrantHook, 100);
            return;
        }}
        
        Chart.defaults.color = '#475569';
        Chart.defaults.scale.grid.color = '#e2e8f0';
        Chart.defaults.font.family = 'Inter, sans-serif';
        const VIBRANT_COLORS = ['#6366f1', '#10b981', '#f43f5e', '#f59e0b', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16'];
        
        Chart.register({{
            id: 'forceVibrantColors',
            beforeUpdate: function(chart) {{
                chart.data.datasets.forEach((dataset, i) => {{
                    if (!dataset.backgroundColor || typeof dataset.backgroundColor === 'string') {{
                        if (['pie', 'doughnut', 'bar', 'polarArea'].includes(chart.config.type) || dataset.type === 'bar') {{
                            dataset.backgroundColor = VIBRANT_COLORS;
                            dataset.borderColor = '#ffffff';
                            dataset.borderWidth = 1;
                        }} else {{
                            dataset.backgroundColor = VIBRANT_COLORS[i % VIBRANT_COLORS.length];
                            dataset.borderColor = VIBRANT_COLORS[i % VIBRANT_COLORS.length];
                            dataset.pointBackgroundColor = VIBRANT_COLORS[i % VIBRANT_COLORS.length];
                            dataset.pointBorderColor = '#ffffff';
                            dataset.pointRadius = 5;
                        }}
                    }}
                }});
            }}
        }});
        
        // Force update any charts that loaded before this script
        if (Chart.instances) {{
            Object.values(Chart.instances).forEach(i => i.update());
        }}
    }}
    registerVibrantHook();
}})();

// Export & Delete Helpers
window.removeCard = function(btn) {{ btn.closest('.card').remove(); }};
window.exportToHTML = function() {{
    const html = document.documentElement.outerHTML;
    const blob = new Blob([html], {{ type: 'text/html' }});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'NexBot_Executive_Dashboard.html';
    a.click();
}};
</script>
"""
        
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
    status = check_system_status()

    print("\n" + "=" * 60)
    print("🤖  NexBot AI — Data Chatbot API (Gemini)")
    print("=" * 60)
    print(f"📍  Port        : {port}")
    print(f"🧠  Model       : {GEMINI_MODEL}")
    print(f"🔑  Gemini Key  : {'✅ set' if GEMINI_API_KEY else '❌ missing — add GEMINI_API_KEY to .env'}")
    print(f"📦  pandas      : {'✅' if PANDAS_AVAILABLE else '❌ (install pandas)'}")
    print(f"🔐  bcrypt      : {'✅' if BCRYPT_AVAILABLE else '⚠️  optional (password hashing)'}")
    print(f"🐘  psycopg2    : {'✅' if POSTGRES_AVAILABLE else '⚠️  optional'}")
    print(f"🐬  pymysql     : {'✅' if MYSQL_AVAILABLE else '⚠️  optional'}")
    print(f"🗄️  pymssql     : {'✅' if PYMSSQL_AVAILABLE else '⚠️  optional (SQL Server)'}")
    print(f"{'✅  Gemini ready!' if status['ready'] else '❌  ' + status.get('error','')}")
    print("─" * 60)
    print(f"🔌  Plugin Reg  : POST /api/v1/register (password-protected)")
    print(f"🗃️  License DB  : {LICENSE_DB_PATH}")
    print(f"📜  Plugin JS   : GET /plugin/chatbot-plugin.js")
    print(f"👤  Admin Keys  : GET /api/v1/admin/keys (X-Admin-Password header)")
    print("=" * 60 + "\n")

    app.run(host='0.0.0.0', port=port, debug=True)
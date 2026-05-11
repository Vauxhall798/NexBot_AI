#!/usr/bin/env python3
"""
NexBot AI — End-to-End Test Suite
Tests all API endpoints + chatbot prompts against the running local server.
"""

import requests
import json
import time
import sys

BASE_URL = "https://nexbot-ai-us.onrender.com"
API_KEY  = "test_key_123"          # hardcoded active key
ADMIN_PW = "NexBot@2026SecurePass"

HEADERS      = {"Content-Type": "application/json", "X-API-Key": API_KEY}
ADMIN_HDRS   = {**HEADERS, "X-Admin-Password": ADMIN_PW}

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"

results = []

def log(status, section, name, detail=""):
    tag = f"[{status}]"
    line = f"  {tag:12} {section:30} {name}"
    if detail:
        line += f"\n             └─ {detail}"
    print(line)
    results.append({"status": status, "section": section, "name": name, "detail": detail})

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ─────────────────────────────────────────────────────────────
# 0. WAKE UP RENDER SERVER
# ─────────────────────────────────────────────────────────────
section("0. WAKE UP SERVER")
print("  Waking up server (can take up to 60s for cold start)...")
try:
    r = requests.get(f"{BASE_URL}/health", timeout=120)
    print("  Server is awake!")
except Exception as e:
    print(f"  Failed to wake up server: {e}")

# ─────────────────────────────────────────────────────────────
# 1. HEALTH CHECK
# ─────────────────────────────────────────────────────────────
section("1. HEALTH CHECK")

try:
    r = requests.get(f"{BASE_URL}/health", timeout=10)
    d = r.json()
    if r.status_code == 200 and d.get("status") in ("healthy", "degraded"):
        log(PASS, "Health", "GET /health", f"status={d['status']} | model={d.get('groq',{}).get('model','?')} | data_sources={d.get('data_sources',0)}")
    else:
        log(FAIL, "Health", "GET /health", f"Unexpected response: {d}")
except Exception as e:
    log(FAIL, "Health", "GET /health", str(e))

# ─────────────────────────────────────────────────────────────
# 2. API KEY VERIFICATION
# ─────────────────────────────────────────────────────────────
section("2. API KEY VERIFICATION")

# 2a. Valid key
try:
    r = requests.post(f"{BASE_URL}/api/v1/verify", headers=HEADERS, json={}, timeout=10)
    d = r.json()
    if r.status_code == 200 and d.get("valid"):
        log(PASS, "Auth", "Valid API key accepted", f"plan={d['subscription']['plan']} | status={d['subscription']['status']}")
    else:
        log(FAIL, "Auth", "Valid API key accepted", str(d))
except Exception as e:
    log(FAIL, "Auth", "Valid API key accepted", str(e))

# 2b. Invalid key should be rejected
try:
    r = requests.post(f"{BASE_URL}/api/v1/verify",
                      headers={"Content-Type": "application/json", "X-API-Key": "invalid_key_xyz"},
                      json={}, timeout=10)
    if r.status_code == 401:
        log(PASS, "Auth", "Invalid key rejected (401)", f"error={r.json().get('error')}")
    else:
        log(FAIL, "Auth", "Invalid key rejected", f"Got {r.status_code}: {r.text[:100]}")
except Exception as e:
    log(FAIL, "Auth", "Invalid key rejected", str(e))

# 2c. Missing key should be rejected
try:
    r = requests.post(f"{BASE_URL}/api/v1/verify",
                      headers={"Content-Type": "application/json"},
                      json={}, timeout=10)
    if r.status_code == 401:
        log(PASS, "Auth", "Missing key rejected (401)")
    else:
        log(FAIL, "Auth", "Missing key rejected", f"Got {r.status_code}")
except Exception as e:
    log(FAIL, "Auth", "Missing key rejected", str(e))

# ─────────────────────────────────────────────────────────────
# 3. PLUGIN REGISTRATION
# ─────────────────────────────────────────────────────────────
section("3. PLUGIN REGISTRATION")

registered_key = None

# 3a. Register with correct password
try:
    payload = {"password": ADMIN_PW, "name": "E2E Tester", "email": "e2e@nexbot.test", "plan": "starter"}
    r = requests.post(f"{BASE_URL}/api/v1/register", headers={"Content-Type": "application/json"}, json=payload, timeout=10)
    d = r.json()
    if r.status_code == 201 and d.get("success"):
        registered_key = d.get("api_key")
        log(PASS, "Registration", "Register with correct password", f"key={registered_key[:16]}... | plan={d.get('plan')}")
    else:
        log(FAIL, "Registration", "Register with correct password", str(d))
except Exception as e:
    log(FAIL, "Registration", "Register with correct password", str(e))

# 3b. Register with wrong password → should be rejected
try:
    payload = {"password": "wrong_password", "name": "Hacker", "email": "hack@test.com"}
    r = requests.post(f"{BASE_URL}/api/v1/register", headers={"Content-Type": "application/json"}, json=payload, timeout=10)
    if r.status_code == 403:
        log(PASS, "Registration", "Wrong password rejected (403)")
    else:
        log(FAIL, "Registration", "Wrong password rejected", f"Got {r.status_code}: {r.text[:100]}")
except Exception as e:
    log(FAIL, "Registration", "Wrong password rejected", str(e))

# 3c. Register without name → should fail
try:
    payload = {"password": ADMIN_PW, "email": "noname@test.com"}
    r = requests.post(f"{BASE_URL}/api/v1/register", headers={"Content-Type": "application/json"}, json=payload, timeout=10)
    if r.status_code == 400:
        log(PASS, "Registration", "Missing name rejected (400)")
    else:
        log(FAIL, "Registration", "Missing name rejected", f"Got {r.status_code}: {r.text[:100]}")
except Exception as e:
    log(FAIL, "Registration", "Missing name rejected", str(e))

# ─────────────────────────────────────────────────────────────
# 4. ADMIN ENDPOINTS
# ─────────────────────────────────────────────────────────────
section("4. ADMIN ENDPOINTS")

# 4a. List all keys
try:
    r = requests.get(f"{BASE_URL}/api/v1/admin/keys", headers=ADMIN_HDRS, timeout=10)
    d = r.json()
    if r.status_code == 200 and d.get("success"):
        log(PASS, "Admin", "List all keys", f"total={d.get('total')} keys in DB")
    else:
        log(FAIL, "Admin", "List all keys", str(d))
except Exception as e:
    log(FAIL, "Admin", "List all keys", str(e))

# 4b. Unauthorized access to admin → should fail
try:
    r = requests.get(f"{BASE_URL}/api/v1/admin/keys",
                     headers={"Content-Type": "application/json", "X-Admin-Password": "wrong"},
                     timeout=10)
    if r.status_code == 403:
        log(PASS, "Admin", "Unauthorized admin access rejected (403)")
    else:
        log(FAIL, "Admin", "Unauthorized admin access rejected", f"Got {r.status_code}")
except Exception as e:
    log(FAIL, "Admin", "Unauthorized admin access rejected", str(e))

# 4c. Revoke the newly registered key
if registered_key:
    try:
        r = requests.delete(f"{BASE_URL}/api/v1/admin/keys",
                            headers=ADMIN_HDRS, json={"api_key": registered_key}, timeout=10)
        d = r.json()
        if r.status_code == 200 and d.get("success"):
            log(PASS, "Admin", "Revoke key via DELETE", f"key={registered_key[:16]}... revoked")
        else:
            log(FAIL, "Admin", "Revoke key via DELETE", str(d))

        # 4d. Try using the revoked key → must get 402
        time.sleep(0.5)
        r2 = requests.post(f"{BASE_URL}/api/v1/verify",
                           headers={"Content-Type": "application/json", "X-API-Key": registered_key},
                           json={}, timeout=10)
        if r2.status_code == 402:
            log(PASS, "Admin", "Revoked key blocked (402)", "Inactive subscription correctly returned")
        else:
            log(FAIL, "Admin", "Revoked key blocked", f"Got {r2.status_code}: {r2.text[:100]}")
    except Exception as e:
        log(FAIL, "Admin", "Revoke key", str(e))

# ─────────────────────────────────────────────────────────────
# 5. DATA SOURCES
# ─────────────────────────────────────────────────────────────
section("5. DATA SOURCES")

try:
    r = requests.get(f"{BASE_URL}/api/v1/data/sources", headers=HEADERS, timeout=10)
    d = r.json()
    if r.status_code == 200 and d.get("success"):
        sources = d.get("sources", [])
        log(PASS, "Data Sources", "List data sources", f"{len(sources)} sources loaded: {[s['name'] for s in sources[:5]]}")
    else:
        log(FAIL, "Data Sources", "List data sources", str(d))
except Exception as e:
    log(FAIL, "Data Sources", "List data sources", str(e))

# ─────────────────────────────────────────────────────────────
# 6. CHATBOT PROMPTS — CONVERSATIONAL
# ─────────────────────────────────────────────────────────────
section("6. CHATBOT — CONVERSATIONAL PROMPTS")

conv_prompts = [
    ("Hello, what can you help me with?",   "greeting"),
    ("What is your name?",                   "identity"),
    ("Thank you for your help!",             "courtesy"),
]

for msg, label in conv_prompts:
    try:
        r = requests.post(f"{BASE_URL}/api/v1/analyze",
                          headers=HEADERS, json={"message": msg}, timeout=30)
        d = r.json()
        if r.status_code == 200 and d.get("success"):
            insight = d.get("insight", "")[:120]
            log(PASS, "Chatbot Conversational", f"Prompt [{label}]", f"reply={insight!r}")
        else:
            log(FAIL, "Chatbot Conversational", f"Prompt [{label}]", str(d))
    except Exception as e:
        log(FAIL, "Chatbot Conversational", f"Prompt [{label}]", str(e))

# ─────────────────────────────────────────────────────────────
# 7. CHATBOT PROMPTS — DATA ANALYSIS (SQL Server tables)
# ─────────────────────────────────────────────────────────────
section("7. CHATBOT — DATA ANALYSIS PROMPTS")

data_prompts = [
    ("How many itineraries are there in total?",           "count itineraries"),
    ("List all unique destinations in the ItineraryMaster table", "unique destinations"),
    ("Which itinerary has the most days?",                 "max days itinerary"),
    ("How many vendors are registered in VendorMaster?",  "vendor count"),
    ("What are the different itinerary categories?",       "categories list"),
    ("Show me all itinerary policies",                     "policies list"),
    ("How many accommodation entries are there?",          "accommodation count"),
    ("List all inclusions from ItineraryInclusion table",  "inclusions list"),
    ("What exclusions are recorded for the itineraries?",  "exclusions list"),
    ("How many days are planned across all itineraries?",  "total days"),
]

for msg, label in data_prompts:
    try:
        r = requests.post(f"{BASE_URL}/api/v1/analyze",
                          headers=HEADERS, json={"message": msg}, timeout=60)
        d = r.json()
        if r.status_code == 200 and d.get("success"):
            insight = d.get("insight", "")[:160]
            cached  = d.get("cached", False)
            log(PASS, "Chatbot Data", f"Prompt [{label}]", f"{'[CACHED] ' if cached else ''}reply={insight!r}")
        else:
            err = d.get("error", d.get("insight", str(d)))[:120]
            log(FAIL, "Chatbot Data", f"Prompt [{label}]", err)
    except Exception as e:
        log(FAIL, "Chatbot Data", f"Prompt [{label}]", str(e))
    time.sleep(1)  # be respectful to Groq rate limits

# ─────────────────────────────────────────────────────────────
# 8. CHATBOT PROMPTS — POSTGRES DATA
# ─────────────────────────────────────────────────────────────
section("8. CHATBOT — POSTGRES DATA PROMPTS")

pg_prompts = [
    ("How many rows are in the sales_analytics table?",     "sales row count"),
    ("What is the total revenue from sales_analytics?",     "total revenue"),
    ("Show me the top 5 sales records",                     "top 5 sales"),
    ("What is the average sales value in sales_analytics?", "avg sales"),
    ("How many rows are in the finops_analytics table?",    "finops row count"),
]

for msg, label in pg_prompts:
    try:
        r = requests.post(f"{BASE_URL}/api/v1/analyze",
                          headers=HEADERS, json={"message": msg}, timeout=60)
        d = r.json()
        if r.status_code == 200 and d.get("success"):
            insight = d.get("insight", "")[:160]
            log(PASS, "Chatbot Postgres", f"Prompt [{label}]", f"reply={insight!r}")
        else:
            err = d.get("error", d.get("insight", str(d)))[:120]
            log(FAIL, "Chatbot Postgres", f"Prompt [{label}]", err)
    except Exception as e:
        log(FAIL, "Chatbot Postgres", f"Prompt [{label}]", str(e))
    time.sleep(1)

# ─────────────────────────────────────────────────────────────
# 9. EDGE CASES
# ─────────────────────────────────────────────────────────────
section("9. EDGE CASES")

# 9a. Empty message
try:
    r = requests.post(f"{BASE_URL}/api/v1/analyze",
                      headers=HEADERS, json={"message": ""}, timeout=10)
    if r.status_code == 400:
        log(PASS, "Edge Cases", "Empty message rejected (400)")
    else:
        log(WARN, "Edge Cases", "Empty message rejected", f"Got {r.status_code}: {r.text[:80]}")
except Exception as e:
    log(FAIL, "Edge Cases", "Empty message rejected", str(e))

# 9b. Nonsense prompt
try:
    r = requests.post(f"{BASE_URL}/api/v1/analyze",
                      headers=HEADERS, json={"message": "asfghjkl xyz random gibberish 12345"}, timeout=30)
    d = r.json()
    if r.status_code == 200 and d.get("success"):
        log(PASS, "Edge Cases", "Nonsense prompt handled", f"reply={d.get('insight','')[:80]!r}")
    else:
        log(WARN, "Edge Cases", "Nonsense prompt handled", str(d)[:100])
except Exception as e:
    log(FAIL, "Edge Cases", "Nonsense prompt handled", str(e))

# 9c. Plugin JS served
try:
    r = requests.get(f"{BASE_URL}/plugin/chatbot-plugin.js", timeout=10)
    if r.status_code == 200 and "AITableChatbot" in r.text:
        log(PASS, "Edge Cases", "Plugin JS served correctly", f"size={len(r.text)} bytes")
    else:
        log(FAIL, "Edge Cases", "Plugin JS served", f"status={r.status_code}")
except Exception as e:
    log(FAIL, "Edge Cases", "Plugin JS served", str(e))

# 9d. CORS OPTIONS preflight
try:
    r = requests.options(f"{BASE_URL}/api/v1/analyze",
                         headers={"Origin": "https://example.com",
                                  "Access-Control-Request-Method": "POST"}, timeout=10)
    if r.status_code in (200, 204):
        log(PASS, "Edge Cases", "CORS preflight (OPTIONS) handled", f"status={r.status_code}")
    else:
        log(WARN, "Edge Cases", "CORS preflight", f"Got {r.status_code}")
except Exception as e:
    log(FAIL, "Edge Cases", "CORS preflight", str(e))

# ─────────────────────────────────────────────────────────────
# 10. SUMMARY
# ─────────────────────────────────────────────────────────────
section("SUMMARY")

total  = len(results)
passed = sum(1 for r in results if PASS in r["status"])
failed = sum(1 for r in results if FAIL in r["status"])
warned = sum(1 for r in results if WARN in r["status"])

print(f"\n  Total Tests : {total}")
print(f"  Passed      : {passed}  ✅")
print(f"  Failed      : {failed}  ❌")
print(f"  Warnings    : {warned}  ⚠️")
print(f"\n  Score       : {passed}/{total} ({100*passed//total}%)")

if failed > 0:
    print("\n  FAILURES:")
    for r in results:
        if FAIL in r["status"]:
            print(f"    ❌ [{r['section']}] {r['name']}")
            if r["detail"]:
                print(f"       {r['detail']}")

print()
sys.exit(0 if failed == 0 else 1)

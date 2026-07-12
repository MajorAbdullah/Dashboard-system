#!/usr/bin/env bash
# ─── Smoke test: Agentic Dashboard AI — PostgreSQL data source ───────────────
# Tests all DB-facing API endpoints against the dollar-postgres-dev container.
#
# Usage:
#   export EMAIL="test-$(date +%s)@example.com"
#   export PASSWORD="test1234"
#   bash scripts/test_db_smoke.sh
#
# Requirements:
#   - docker running
#   - dollar-postgres-dev container up (port 5432)
#   - backend running on localhost:8000
#   - python3 + jq or python3 for JSON parsing
#
# The script creates a throwaway account so it can run against a clean backend.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

BASE="${BASE:-http://localhost:8000/api}"
EMAIL="${EMAIL:-smoke-$(date +%s)@example.com}"
PASSWORD="${PASSWORD:-test1234}"
# Backend runs on host, so use localhost (not host.docker.internal)
DB_URL="postgresql://postgres:postgres@localhost:5432/onedollarstore"

TABLE="${TABLE:-products}"   # default table to query
pass=0; fail=0

ok()   { echo "  ✓ $1"; pass=$((pass+1)); }
nok()  { echo "  ✗ $1"; fail=$((fail+1)); }
json() { python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin),indent=2))" 2>/dev/null || cat; }
extract() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)" 2>/dev/null; }

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   Agentic Dashboard AI — DB Source Smoke Test               ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Email: $EMAIL"
echo "║  DB:    $DB_URL  ($TABLE)"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Health check ──────────────────────────────────────────────────────────
echo "── 1. Backend reachable ──"
HEALTH=$(curl -sf --max-time 5 "$BASE/me" 2>&1) && ok "Backend is up" || {
  # 401 means the server is up (just not authenticated)
  if curl -s --max-time 5 "$BASE/me" 2>&1 | grep -q "Not authenticated\|detail"; then
    ok "Backend is up (401 = server running)"
  else
    nok "Backend unreachable at $BASE"
  fi
}

# ── 2. DB test connection ────────────────────────────────────────────────────
echo ""
echo "── 2. POST /api/db/test ──"
RES=$(curl -sf --max-time 10 -X POST "$BASE/db/test" \
  -H "Content-Type: application/json" \
  -d "{\"conn_string\": \"$DB_URL\"}") \
  && ok "DB connection test passed" \
  || nok "DB connection test failed"

# ── 3. DB list tables ────────────────────────────────────────────────────────
echo ""
echo "── 3. POST /api/db/tables ──"
RES=$(curl -sf --max-time 10 -X POST "$BASE/db/tables" \
  -H "Content-Type: application/json" \
  -d "{\"conn_string\": \"$DB_URL\"}") || { nok "List tables failed"; exit 1; }
echo "$RES" | python3 -c "
import sys,json
d = json.load(sys.stdin)
tables = [t['table_name'] for t in d.get('tables',[])]
print(f'  → {len(tables)} tables found')
assert len(tables) > 0, 'No tables'
assert '$TABLE' in tables, 'Expected table missing'
" && ok "Tables listed (${TABLE} present)" || nok "Tables missing"

# ── 4. Signup with DB credentials ────────────────────────────────────────────
echo ""
echo "── 4. POST /api/auth/signup (with DB fields) ──"
RES=$(curl -sf --max-time 10 -X POST "$BASE/auth/signup" \
  -H "Content-Type: application/json" \
  -d "{
    \"email\": \"$EMAIL\",
    \"password\": \"$PASSWORD\",
    \"name\": \"Smoke Tester\",
    \"company\": \"SmokeCorp\",
    \"db_type\": \"postgresql\",
    \"db_connection_string\": \"$DB_URL\",
    \"db_table_name\": \"$TABLE\"
  }") || { nok "Signup failed"; exit 1; }
TOKEN=$(echo "$RES" | extract "['token']")
echo "  → Token: ${TOKEN:0:16}…"
echo "$RES" | python3 -c "
import sys,json
u = json.load(sys.stdin)['user']
assert u['has_db'] == True, 'has_db should be true'
assert u['db_type'] == 'postgresql'
assert u['db_table_name'] == '$TABLE'
" && ok "User created with DB fields" || nok "User DB fields missing"

# ── 5. GET /me ───────────────────────────────────────────────────────────────
echo ""
echo "── 5. GET /api/me ──"
curl -sf --max-time 5 "$BASE/me" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
u = json.load(sys.stdin)['user']
assert u['has_db'] == True
assert '***' in (u.get('db_host_masked') or ''), 'db_host_masked should be present and masked, not the raw connection string'
assert u['db_table_name'] == '$TABLE'
" && ok "Profile returns DB fields (masked)" || nok "DB fields missing from /me"

# ── 6. GET /my-datasets ──────────────────────────────────────────────────────
echo ""
echo "── 6. GET /api/my-datasets ──"
curl -sf --max-time 5 "$BASE/my-datasets" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
d = json.load(sys.stdin)
assert 'db' in d, 'db key missing'
assert d['db']['type'] == 'postgresql'
assert d['db']['table_name'] == '$TABLE'
" && ok "my-datasets returns DB info" || nok "DB info missing from my-datasets"

# ── 7. Create session (DB mode) ──────────────────────────────────────────────
echo ""
echo "── 7. POST /api/session (source_type=database) ──"
RES=$(curl -sf --max-time 30 -X POST "$BASE/session" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"source_type\": \"database\",
    \"conn_string\": \"$DB_URL\",
    \"table_name\": \"$TABLE\"
  }") || { nok "Session creation failed"; exit 1; }
SID=$(echo "$RES" | extract "['session_id']")
echo "  → Session: $SID"
echo "$RES" | python3 -c "
import sys,json
d = json.load(sys.stdin)
assert d['source_type'] == 'database'
assert d['dataset_name'] == '$TABLE'
assert d['profile'] is not None
assert len(d['suggested_queries']) > 0
" && ok "Session created with profile" || nok "Session/profile incomplete"

# ── 8. Generate ──────────────────────────────────────────────────────────────
echo ""
echo "── 8. POST /api/generate ──"
RES=$(curl -sf --max-time 120 -X POST "$BASE/generate" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"session_id\": \"$SID\",
    \"goal\": \"Show me top selling products by quantity\"
  }") || { nok "Generate failed"; exit 1; }
echo "$RES" | python3 -c "
import sys,json
d = json.load(sys.stdin)
drafts = d.get('drafts',[])
assert len(drafts) >= 1, 'Expected at least 1 draft'
for dr in drafts:
    assert dr.get('exact') == True, 'DB mode should be exact'
    assert dr.get('confidence') == 95, 'DB mode confidence should be 95'
print(f'  → {len(drafts)} drafts generated, all exact=true, confidence=95')
" && ok "Generate produced exact drafts" || nok "Generate drafts wrong"

# Save draft count for next step
DRAFT_COUNT=$(echo "$RES" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('drafts',[])))")
echo "  → $DRAFT_COUNT drafts"

# ── 9. Refine ────────────────────────────────────────────────────────────────
echo ""
echo "── 9. POST /api/refine ──"
RES=$(curl -sf --max-time 120 -X POST "$BASE/refine" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"session_id\": \"$SID\",
    \"message\": \"Add a bar chart of revenue by product category\"
  }") || { nok "Refine failed"; exit 1; }
echo "$RES" | python3 -c "
import sys,json
d = json.load(sys.stdin)
assert 'draft' in d, 'Expected draft in refine response'
dr = d['draft']
print(f'  → Refined: {dr.get(\"title\",\"?\")} ({dr.get(\"type\",\"?\")})')
" && ok "Refine produced a draft" || nok "Refine draft missing"

# ── 10. Edge: no key mode ────────────────────────────────────────────────────
echo ""
echo "── 10. Edge: session without table_name ──"
RES=$(curl -sf --max-time 5 -X POST "$BASE/session" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"source_type": "database", "conn_string": "'"$DB_URL"'", "table_name": ""}' 2>&1) \
  && nok "Empty table_name should fail" \
  || ok "Empty table_name rejected correctly"

# ── 11. Edge: bad connection string ──────────────────────────────────────────
echo ""
echo "── 11. Edge: bad connection string ──"
RES=$(curl -sf --max-time 5 -X POST "$BASE/db/test" \
  -H "Content-Type: application/json" \
  -d '{"conn_string": "postgresql://bad:bad@localhost:9999/bad"}' 2>&1) \
  && nok "Bad connection should fail" \
  || ok "Bad connection string rejected correctly"

# ── 12. Edge: missing auth for protected endpoints ───────────────────────────
echo ""
echo "── 12. Edge: unauthenticated request ──"
RES=$(curl -sf --max-time 5 "$BASE/me" 2>&1) \
  && nok "Unauthenticated /me should fail" \
  || ok "Unauthenticated /me rejected"

# ── 13. Guardrail: generate() on an unknown session returns soft not_connected ──
echo ""
echo "── 13. Edge: generate on unknown/missing session ──"
RES=$(curl -sf --max-time 10 -X POST "$BASE/generate" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"session_id": "sess_does_not_exist", "goal": "anything"}') || { nok "Generate request failed transport-level"; RES='{}'; }
echo "$RES" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('status') == 'not_connected', f\"expected not_connected, got {d.get('status')}\"
assert 'drafts' not in d, 'should not have run the pipeline'
" && ok "Unknown session returns soft not_connected status" || nok "Guardrail response wrong shape"

# ── 14. Workspace persists chatMessages ──
echo ""
echo "── 14. PUT/GET /api/workspace roundtrips chatMessages ──"
curl -sf --max-time 10 -X PUT "$BASE/workspace" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"widgets": [], "drafts": [], "chatMessages": [{"role": "user", "text": "hi"}]}' > /dev/null
RES=$(curl -sf --max-time 10 "$BASE/workspace" -H "Authorization: Bearer $TOKEN")
echo "$RES" | python3 -c "
import sys, json
d = json.load(sys.stdin)['workspace']
msgs = d.get('chatMessages', [])
assert len(msgs) == 1 and msgs[0]['text'] == 'hi', f'chatMessages did not round-trip: {msgs}'
" && ok "chatMessages persisted and restored" || nok "chatMessages missing from workspace"

# ── 15. POST /api/chat (direct Q&A over the connected table) ──
echo ""
echo "── 15. POST /api/chat ──"
RES=$(curl -sf --max-time 120 -X POST "$BASE/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"session_id\": \"$SID\",
    \"message\": \"How many rows are in this table?\"
  }") || { nok "Chat failed"; exit 1; }
echo "$RES" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d.get('status') == 'ready', f\"expected ready, got {d.get('status')}\"
assert d.get('answer'), 'answer should be non-empty'
print(f'  → answer: {d[\"answer\"][:80]}')
" && ok "Chat produced a direct answer" || nok "Chat response missing/malformed"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
printf "║  %2d passed  ·  %2d failed                                    ║\n" $pass $fail
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
if (( fail > 0 )); then exit 1; fi

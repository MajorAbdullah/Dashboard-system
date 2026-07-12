# Open-Access Onboarding, Data Guardrails, Chat, and Chart-Type Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the hard onboarding/connect gate, add a readiness guardrail before chart/chat generation, ship a direct "chat with your data" mode alongside chart generation, and let users switch a generated chart's visual type after creation.

**Architecture:** A pure-logic `classify_readiness()` guardrail (backend) gates the existing `/api/generate`/`/api/refine` routes and a new `/api/chat` route, replacing hard errors with soft, typed `{status, message}` responses. The frontend's Connect modal is retired entirely in favor of a persistent composer bar (Mode + Source/Dataset dropdowns) that reuses the existing connect state machine verbatim. Chat reuses the exact same retrieval code path chart generation already uses (Inflectiv semantic search / Postgres SQL-writer), just asking for a written answer instead of a `ChartSpec`. Chart-type switching is a pure frontend re-render — no backend involvement — restricted to types whose required fields (`data[]` or `series[]`) the spec already has populated.

**Tech Stack:** FastAPI + Pydantic (backend), psycopg2, custom `dc-runtime` HTML/JS templating compiled to React (`h = React.createElement`) for the frontend (no build step, no existing test framework — verification is via `pytest` for pure backend logic, the project's existing shell-based smoke-test pattern (`scripts/test_db_smoke.sh`) for API integration, and Playwright MCP browser automation for UI behavior).

## Global Constraints

- Every change lands on the `dev` branch first via `git commit` + `git push origin dev`. Never push directly to `main` — this is a standing project rule (see `docs/superpowers/specs/2026-07-11-open-access-guardrails-chat-chart-switching-design.md`).
- No new chart types beyond the existing 12 (`kpi, area, line, bar, donut, funnel, heatmap, forecast, insight, risk, summary, table`).
- Chat has no new persistent DB table — messages ride the existing `workspace` JSONB autosave (same durability as `widgets`/`drafts` today).
- Chart-type switching never calls the backend — it's a pure client-side re-render using data the `ChartSpec` already has.
- Backend modules use flat imports (`import sessions`, `from schemas import X`) — no package prefixes. Follow this convention in all new backend files.
- Follow the existing dc-runtime template conventions exactly: `<sc-if value="{{ expr }}" hint-placeholder-val="{{ default }}">`, `<sc-for list="{{ list }}" as="item" hint-placeholder-count="N">`, `{{ binding }}`, and a `renderVals()` method that returns the full flat props object consumed by the template — every new binding used in markup MUST appear in `renderVals()`'s returned object or the template won't see it.

---

## File Structure

Backend (new/modified):
- `backend/guardrails.py` — **new**. `classify_readiness()` + `READINESS_MESSAGES`. Pure logic, no I/O.
- `backend/sessions.py` — add `record_count` field to `Session`.
- `backend/datasource.py` — add `row_count` property to `DatabaseDataSource`.
- `backend/main.py` — guardrail-gate `/api/generate`/`/api/refine`, add `/api/chat`.
- `backend/schemas.py` — add `ChatRequest`, `ChatAnswer`, `WorkspaceSave.chatMessages`.
- `backend/prompts.py` — add `CHAT_DB_ANSWERER`, `CHAT_INFLECTIV_ANSWERER`.
- `backend/pipeline.py` — extract `_retrieve_for_message()` (shared by `refine()` and new `chat()`), add `chat()`.
- `backend/routes_app.py` — persist `chatMessages` in `PUT /workspace`.
- `backend/tests/test_guardrails.py` — **new**. pytest unit tests for `classify_readiness()`.
- `backend/pytest.ini` — **new**. `pythonpath = .` so flat imports resolve under pytest.
- `backend/requirements.txt` — add `pytest`.
- `scripts/test_db_smoke.sh` — extend with guardrail + chat + workspace smoke cases.

Frontend (modified):
- `frontend/Agentic Auth.dc.html` — Step 2 (data source) becomes optional.
- `frontend/Agentic Dashboard AI.dc.html` — remove the blocking Connect modal, add a persistent connect banner, add the composer bar (Mode + Source/Dataset popover replacing the modal), add the Chat panel, add chart-type switching.

No new frontend files — this dc-runtime app is single-file-per-page by convention; splitting would fight the existing pattern.

---

### Task 1: Guardrail classification + `Session.record_count`

**Files:**
- Modify: `backend/sessions.py`
- Create: `backend/guardrails.py`
- Create: `backend/tests/test_guardrails.py`
- Create: `backend/pytest.ini`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Produces: `guardrails.classify_readiness(session: Optional[sessions.Session]) -> Literal["not_connected", "no_source_data", "ready"]`, `guardrails.READINESS_MESSAGES: dict[str, str]` (keys: `"not_connected"`, `"no_source_data"`, `"unreachable"`). `sessions.Session.record_count: int` (new field, default `0`).

- [ ] **Step 1: Add `pytest` to requirements and create the pytest config**

Edit `backend/requirements.txt`, after the `psycopg2-binary==2.9.10` line:
```
psycopg2-binary==2.9.10
sqlparse==0.5.1
pytest==8.3.4
redis==5.2.1
```

Create `backend/pytest.ini`:
```ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_guardrails.py`:
```python
from guardrails import classify_readiness
from sessions import Session


def test_classify_readiness_no_session():
    assert classify_readiness(None) == "not_connected"


def test_classify_readiness_empty_source():
    sess = Session(session_id="sess_1", record_count=0)
    assert classify_readiness(sess) == "no_source_data"


def test_classify_readiness_negative_treated_as_empty():
    sess = Session(session_id="sess_1", record_count=-1)
    assert classify_readiness(sess) == "no_source_data"


def test_classify_readiness_ready():
    sess = Session(session_id="sess_1", record_count=42)
    assert classify_readiness(sess) == "ready"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/pip install pytest==8.3.4 && .venv/bin/pytest tests/test_guardrails.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'guardrails'` (and `Session()` doesn't accept `record_count` yet).

- [ ] **Step 4: Add `record_count` to `Session`**

In `backend/sessions.py`, the `Session` dataclass currently ends with `table_name: str = ""`. Add one field after it:
```python
@dataclass
class Session:
    session_id: str
    global_key: str = ""
    dataset_id: int = 0
    dataset_name: str = ""
    profile: Optional[DatasetProfile] = None
    knowledge_source_count: int = 0
    source_type: str = "inflectiv"
    conn_string: str = ""
    table_name: str = ""
    record_count: int = 0
```

Update `create()` so Inflectiv sessions get `record_count` populated from the same `knowledge_source_count` value at creation time (Database sessions get it wired in Task 2):
```python
def create(global_key: str = "", dataset: Optional[dict] = None,
           source_type: str = "inflectiv", conn_string: str = "",
           table_name: str = "") -> Session:
    sid = "sess_" + secrets.token_urlsafe(16)
    ks_count = dataset.get("knowledge_source_count", 0) if dataset else 0
    s = Session(
        session_id=sid,
        global_key=global_key,
        dataset_id=dataset["id"] if dataset else 0,
        dataset_name=dataset.get("name", "") if dataset else table_name,
        knowledge_source_count=ks_count,
        source_type=source_type,
        conn_string=conn_string,
        table_name=table_name,
        record_count=ks_count,
    )
    _sessions[sid] = s
    return s
```

- [ ] **Step 5: Create `backend/guardrails.py`**

```python
"""Data-readiness guardrail: decides whether a session has real, queryable
data before chart/chat generation runs the (costly) retrieval + LLM pipeline.
"""
from __future__ import annotations

from typing import Literal, Optional

from sessions import Session

ReadinessState = Literal["not_connected", "no_source_data", "unreachable", "ready"]

READINESS_MESSAGES: dict[str, str] = {
    "not_connected": "Connect a data source to get started.",
    "no_source_data": "The connected source has no data yet — check your dataset or table.",
    "unreachable": "Could not reach the connected data source. Try again in a moment.",
}


def classify_readiness(session: Optional[Session]) -> ReadinessState:
    """Pure classification — no I/O. 'unreachable' is never returned here; the
    route handler reports it itself when a retrieval call raises (see main.py)."""
    if session is None:
        return "not_connected"
    if session.record_count <= 0:
        return "no_source_data"
    return "ready"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_guardrails.py -v`
Expected: `4 passed`

- [ ] **Step 7: Commit**

```bash
cd "/Users/abdullah/Desktop/Dashboard system"
git add backend/guardrails.py backend/sessions.py backend/tests/test_guardrails.py backend/pytest.ini backend/requirements.txt
git commit -m "Add data-readiness guardrail (classify_readiness) with pytest coverage

Session gains record_count, populated from knowledge_source_count for
Inflectiv sessions at creation time (database sessions wired in the next
commit). classify_readiness() is pure logic — not_connected / no_source_data
/ ready — with no I/O, so it's unit-testable without a live backend.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push origin dev
```

---

### Task 2: Wire `record_count` for database sessions + apply the guardrail to `/api/generate` and `/api/refine`

**Files:**
- Modify: `backend/datasource.py`
- Modify: `backend/main.py`
- Modify: `scripts/test_db_smoke.sh`

**Interfaces:**
- Consumes: `guardrails.classify_readiness`, `guardrails.READINESS_MESSAGES` (Task 1). `sessions.Session.record_count` (Task 1).
- Produces: `datasource.DatabaseDataSource.row_count -> int` property. `/api/generate` and `/api/refine` now return `{"status": "not_connected"|"no_source_data"|"unreachable"|"ready", ...}` instead of raising 401 on an unknown/missing session. On `status != "ready"` the body is exactly `{"status": ..., "message": ...}` — no `drafts`/`draft` key.

- [ ] **Step 1: Add `row_count` property to `DatabaseDataSource`**

In `backend/datasource.py`, `DatabaseDataSource` already has `source_name` and `size_estimate` properties near the end of the class (after `query()`). Add a third property right after `size_estimate`:
```python
    @property
    def size_estimate(self) -> str:
        return "small"

    @property
    def row_count(self) -> int:
        return (self._schema or {}).get("row_count", 0)
```

- [ ] **Step 2: Set `sess.record_count` after profiling in `/api/session`'s database branch**

In `backend/main.py`, `create_session()`'s database branch currently reads:
```python
        sess = sessions.create(global_key=key, source_type="database",
                               conn_string=conn_string, table_name=table_name)
        ds = datasource.DatabaseDataSource(conn_string, table_name)
        profile = None
        if config.have_llm():
            try:
                profile = await ds.get_profile(emit=None)
                sess.profile = profile
            except Exception:
                pass
```
Change to also record `row_count`:
```python
        sess = sessions.create(global_key=key, source_type="database",
                               conn_string=conn_string, table_name=table_name)
        ds = datasource.DatabaseDataSource(conn_string, table_name)
        profile = None
        if config.have_llm():
            try:
                profile = await ds.get_profile(emit=None)
                sess.profile = profile
                sess.record_count = ds.row_count
            except Exception:
                pass
```

- [ ] **Step 3: Replace `_require_session`'s hard 401 with the guardrail in `/api/generate` and `/api/refine`**

In `backend/main.py`, add the import (next to the existing `from schemas import ...` line):
```python
from guardrails import READINESS_MESSAGES, classify_readiness
```

Replace the existing `_require_session` function:
```python
def _require_session(session_id: str) -> sessions.Session:
    sess = sessions.get(session_id)
    if not sess:
        raise HTTPException(401, "Unknown or expired session. Reconnect on the Connect screen.")
    if not config.have_llm():
        raise HTTPException(503, "No LLM provider configured. Set FIREWORKS_API_KEY "
                                 "(preferred) or OPENROUTER_API_KEY in backend/.env.")
    return sess
```
with:
```python
def _require_llm() -> None:
    if not config.have_llm():
        raise HTTPException(503, "No LLM provider configured. Set FIREWORKS_API_KEY "
                                 "(preferred) or OPENROUTER_API_KEY in backend/.env.")
```

Replace `/api/generate`:
```python
@app.post("/api/generate")
async def generate(req: GenerateRequest, user: Optional[dict] = Depends(optional_user)):
    sess = sessions.get(req.session_id)
    state = classify_readiness(sess)
    if state != "ready":
        return {"status": state, "message": READINESS_MESSAGES[state]}
    _require_llm()
    ds = make_datasource(sess)
    emit = agentbus.make_emit(req.job_id)
    try:
        result = await pipeline.generate(ds, req.goal, sess.profile, emit)
    except Exception as e:
        await agentbus.finish(req.job_id, 0)
        print(f"[generate] pipeline error: {e}")
        return {"status": "unreachable", "message": READINESS_MESSAGES["unreachable"]}
    await agentbus.finish(req.job_id, len(result["drafts"]))
    if user:
        _persist_drafts(user["id"], req.goal, result.get("drafts", []))
    result["job_id"] = req.job_id
    result["status"] = "ready"
    return result
```

Replace `/api/refine`:
```python
@app.post("/api/refine")
async def refine(req: RefineRequest):
    sess = sessions.get(req.session_id)
    state = classify_readiness(sess)
    if state != "ready":
        return {"status": state, "message": READINESS_MESSAGES[state]}
    _require_llm()
    ds = make_datasource(sess)
    emit = agentbus.make_emit(req.job_id)
    try:
        result = await pipeline.refine(ds, req.message, emit)
    except Exception as e:
        await agentbus.finish(req.job_id, 0)
        print(f"[refine] pipeline error: {e}")
        return {"status": "unreachable", "message": READINESS_MESSAGES["unreachable"]}
    await agentbus.finish(req.job_id, 1)
    result["status"] = "ready"
    return result
```

- [ ] **Step 4: Add a smoke test case for the guardrail**

In `scripts/test_db_smoke.sh`, insert a new step right before the `# ── Summary ──` block at the end of the file:
```bash
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
```

- [ ] **Step 5: Run the smoke test end to end**

Run: `cd "/Users/abdullah/Desktop/Dashboard system" && make start` (waits for Postgres/Redis + backend on :8000), then in another terminal:
`bash scripts/test_db_smoke.sh`
Expected: all 13 steps report `✓` (0 failed). Step 8 (`Generate produced exact drafts`) confirms the `record_count`/guardrail wiring didn't break the existing happy path; step 13 confirms the new soft-failure shape.

- [ ] **Step 6: Commit**

```bash
cd "/Users/abdullah/Desktop/Dashboard system"
git add backend/datasource.py backend/main.py scripts/test_db_smoke.sh
git commit -m "Gate /api/generate and /api/refine with the readiness guardrail

Database sessions now record row_count as record_count after profiling
(mirroring the Inflectiv path's knowledge_source_count). generate/refine
return a typed {status, message} instead of a bare 401 when there's no
session or the connected source is empty, so the frontend can show a
specific inline message instead of a generic error.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push origin dev
```

---

### Task 3: Persist chat messages via the existing workspace autosave

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/routes_app.py`
- Modify: `scripts/test_db_smoke.sh`

**Interfaces:**
- Produces: `WorkspaceSave.chatMessages: list` (new field, default `[]`). `PUT /api/workspace` now stores `chatMessages` alongside `widgets`/`drafts`; `GET /api/workspace` already returns the whole stored blob unchanged, so no read-side code changes are needed.

- [ ] **Step 1: Add `chatMessages` to `WorkspaceSave`**

In `backend/schemas.py`, `WorkspaceSave` currently reads:
```python
class WorkspaceSave(BaseModel):
    model_config = {"extra": "ignore"}
    widgets: list = Field(default_factory=list)
    drafts: list = Field(default_factory=list)
```
Change to:
```python
class WorkspaceSave(BaseModel):
    model_config = {"extra": "ignore"}
    widgets: list = Field(default_factory=list)
    drafts: list = Field(default_factory=list)
    chatMessages: list = Field(default_factory=list)
```

- [ ] **Step 2: Store `chatMessages` in `put_workspace`**

In `backend/routes_app.py`, `put_workspace` currently reads:
```python
@router.put("/workspace")
def put_workspace(req: WorkspaceSave, user: dict = Depends(current_user)):
    db.execute("UPDATE users SET workspace=%s WHERE id=%s",
               (db.Json({"widgets": req.widgets, "drafts": req.drafts}), user["id"]))
    return {"ok": True}
```
Change to:
```python
@router.put("/workspace")
def put_workspace(req: WorkspaceSave, user: dict = Depends(current_user)):
    db.execute("UPDATE users SET workspace=%s WHERE id=%s",
               (db.Json({"widgets": req.widgets, "drafts": req.drafts,
                         "chatMessages": req.chatMessages}), user["id"]))
    return {"ok": True}
```

- [ ] **Step 3: Add a smoke test for the round-trip**

In `scripts/test_db_smoke.sh`, insert after the step-13 block added in Task 2 (still before `# ── Summary ──`):
```bash
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
```

- [ ] **Step 4: Run the smoke test**

Run: `bash scripts/test_db_smoke.sh` (backend must already be running via `make start`)
Expected: 14 steps, 0 failed.

- [ ] **Step 5: Commit**

```bash
cd "/Users/abdullah/Desktop/Dashboard system"
git add backend/schemas.py backend/routes_app.py scripts/test_db_smoke.sh
git commit -m "Persist chat messages through the existing workspace autosave

WorkspaceSave gains chatMessages (default []), stored alongside widgets and
drafts in the same JSONB blob. No new table — same durability model the
canvas already has.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push origin dev
```

---

### Task 4: Chat pipeline + `POST /api/chat`

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/prompts.py`
- Modify: `backend/pipeline.py`
- Modify: `backend/main.py`
- Modify: `scripts/test_db_smoke.sh`

**Interfaces:**
- Consumes: `guardrails.classify_readiness`, `guardrails.READINESS_MESSAGES` (Task 1/2). `datasource.BaseDataSource.query()` (existing).
- Produces: `schemas.ChatRequest(session_id: str, message: str)`, `schemas.ChatAnswer(answer: str, chart: Optional[ChartSpec], grounded: bool, confidence: int)`. `pipeline.chat(datasource, message, emit) -> dict` with shape `{"answer": str, "chart": dict|None, "confidence": int, "sources": list|None}`. `POST /api/chat` returns `{"status": "ready", "answer": ..., "chart": ..., "confidence": ..., "sources": ...}` on success, or `{"status": ..., "message": ...}` on guardrail failure — same envelope shape as `/api/generate`/`/api/refine`.

- [ ] **Step 1: Add `ChatRequest` and `ChatAnswer` to `schemas.py`**

Add `ChatRequest` near the other request models — right after `RefineRequest`:
```python
class RefineRequest(BaseModel):
    session_id: str
    message: str
    job_id: Optional[str] = None


class ChatRequest(BaseModel):
    session_id: str
    message: str
```

Add `ChatAnswer` right after the `ChartSpec` class definition (it references `ChartSpec`, so must come after it), before the `# ---------- planning ----------` section comment:
```python
class ChatAnswer(BaseModel):
    model_config = {"extra": "ignore"}
    answer: str
    chart: Optional[ChartSpec] = None
    grounded: bool = True
    confidence: int = 70


# ---------- planning ----------
class PlannedChart(BaseModel):
    ...
```

- [ ] **Step 2: Add the two chat prompts**

Append to the end of `backend/prompts.py`, after `DB_PROFILER`:
```python
CHAT_DB_ANSWERER = """You are answering a direct question about data in a PostgreSQL
table, using exact query results (not a sample). Rules:
- Answer in plain written language, 1-3 sentences, with the key number(s) stated
  explicitly (e.g. "Total sales over the last 3 years were $1,245,000, up 12% from
  the prior period.").
- The results are exact — every value is read directly from the database. Set
  grounded=true and confidence=95.
- If the answer is naturally a trend over time or a breakdown across more than a
  couple of categories, ALSO fill `chart` with a ChartSpec (bar/donut/line/area as
  fits the shape) summarizing it — otherwise leave `chart` null.
- If the query results are empty, say so honestly instead of guessing a number.
- Do not invent a data source name.
"""

CHAT_INFLECTIV_ANSWERER = """You are answering a direct question by grounding it in
retrieved passages from the user's dataset (semantic search over embeddings, not
exact tabular data). Rules:
- Answer in plain written language, 1-3 sentences, using ONLY values supported by the
  passages. If you must infer or estimate, say so in the answer and set grounded=false;
  if every value is read directly from a passage, set grounded=true.
- If the passages do not support an answer, say plainly that the dataset doesn't
  contain that information — do not guess.
- If the answer is naturally a trend or breakdown supported by multiple passages,
  you MAY additionally fill `chart` with a ChartSpec — otherwise leave `chart` null.
- Do not invent a data source name.
"""
```

- [ ] **Step 3: Extract `_retrieve_for_message()` and refactor `refine()`**

In `backend/pipeline.py`, update the schemas import line:
```python
from schemas import ChartSpec, ChatAnswer, DashboardPlan, DatasetProfile, SourceRef
```

Replace the entire existing `refine()` function (currently the last function in the file) with:
```python
async def _retrieve_for_message(datasource: BaseDataSource, message: str, emit) -> tuple[list[dict], str, str]:
    """Shared by refine() and chat(): keyword-augmented retrieval for a free-form
    message. Returns (pooled chunks sorted by score desc, source_type, source_name)."""
    stop = {"which", "what", "who", "where", "when", "why", "how", "do", "does", "did",
            "is", "are", "the", "a", "an", "of", "on", "in", "to", "for", "and", "or",
            "by", "with", "top", "focus", "show", "me", "our", "their", "this", "that"}
    kw = " ".join(w for w in message.lower().replace("?", "").split() if w not in stop)
    queries = [message]
    if kw and cache.normalize(kw) != cache.normalize(message):
        queries.append(kw)

    retrieved = await datasource.query("", queries, config.DEFAULT_TOP_K, emit)
    chunks, seenc = [], set()
    for q in queries:
        for c in retrieved.get(q, []):
            k = (c.get("knowledge_source_id"), c.get("chunk_index"), c.get("text", "")[:50])
            if k not in seenc:
                seenc.add(k)
                chunks.append(c)
    chunks.sort(key=lambda c: c.get("score", 0), reverse=True)
    source_type = getattr(datasource, '_conn_string', None) and "database" or "inflectiv"
    return chunks, source_type, datasource.source_name


async def refine(datasource: BaseDataSource, message: str, emit) -> dict:
    await emit("Investigating your question")
    chunks, source_type, source_name = await _retrieve_for_message(datasource, message, emit)

    if source_type == "database":
        results_text = "\n".join(c.get("text", "") for c in chunks[:20]) or "(no results)"
        user = (
            f"Follow-up question: {message!r}. data source={source_name!r}.\n\n"
            f"Query results:\n{results_text}"
        )
    else:
        user = (
            f"Follow-up question: {message!r}. data source={source_name!r}.\n\n"
            f"Retrieved passages:\n{_format_chunks(chunks)}"
        )
    spec = await chat_json(prompts.REFINER, user, ChartSpec)
    spec.source = source_name
    spec.sources = [
        SourceRef(text=c.get("text", "")[:400], score=c.get("score", 0.0),
                  knowledge_source_id=c.get("knowledge_source_id"))
        for c in chunks[:6]
    ]
    spec.confidence = 95 if source_type == "database" else _confidence(chunks, spec.grounded)
    await emit("Done", "done")
    return {"draft": spec.model_dump(exclude_none=True)}


async def chat(datasource: BaseDataSource, message: str, emit) -> dict:
    """Direct Q&A over the connected source: reuses the same retrieval refine()
    uses, but asks for a written answer (with an optional attached chart) instead
    of forcing everything into a ChartSpec."""
    await emit("Answering your question")
    chunks, source_type, source_name = await _retrieve_for_message(datasource, message, emit)

    if source_type == "database":
        prompt = prompts.CHAT_DB_ANSWERER
        results_text = "\n".join(c.get("text", "") for c in chunks[:20]) or "(no results)"
        user = f"Question: {message!r}. data source={source_name!r}.\n\nQuery results:\n{results_text}"
    else:
        prompt = prompts.CHAT_INFLECTIV_ANSWERER
        user = f"Question: {message!r}. data source={source_name!r}.\n\nRetrieved passages:\n{_format_chunks(chunks)}"

    result = await chat_json(prompt, user, ChatAnswer)
    result.confidence = 95 if source_type == "database" else _confidence(chunks, result.grounded)
    sources = [
        SourceRef(text=c.get("text", "")[:400], score=c.get("score", 0.0),
                  knowledge_source_id=c.get("knowledge_source_id"))
        for c in chunks[:6]
    ]
    if result.chart:
        result.chart.source = source_name
        result.chart.sources = sources
        result.chart.confidence = result.confidence
    await emit("Done", "done")
    return {
        "answer": result.answer,
        "chart": result.chart.model_dump(exclude_none=True) if result.chart else None,
        "confidence": result.confidence,
        "sources": [s.model_dump() for s in sources] if source_type != "database" else None,
    }
```

- [ ] **Step 4: Add `POST /api/chat` to `main.py`**

Update the schemas import line:
```python
from schemas import ChatRequest, DatasetsRequest, GenerateRequest, RefineRequest, SessionRequest
```

Add the route right after `/api/refine`:
```python
@app.post("/api/chat")
async def chat(req: ChatRequest):
    sess = sessions.get(req.session_id)
    state = classify_readiness(sess)
    if state != "ready":
        return {"status": state, "message": READINESS_MESSAGES[state]}
    _require_llm()
    ds = make_datasource(sess)
    emit = agentbus.make_emit(None)
    try:
        result = await pipeline.chat(ds, req.message, emit)
    except Exception as e:
        print(f"[chat] pipeline error: {e}")
        return {"status": "unreachable", "message": READINESS_MESSAGES["unreachable"]}
    result["status"] = "ready"
    return result
```

- [ ] **Step 5: Add a smoke test for `/api/chat`**

In `scripts/test_db_smoke.sh`, insert after the step-14 block added in Task 3 (still before `# ── Summary ──`):
```bash
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
```

- [ ] **Step 6: Run the full smoke test**

Run: `bash scripts/test_db_smoke.sh` (backend running via `make start`)
Expected: 15 steps, 0 failed.

- [ ] **Step 7: Commit**

```bash
cd "/Users/abdullah/Desktop/Dashboard system"
git add backend/schemas.py backend/prompts.py backend/pipeline.py backend/main.py scripts/test_db_smoke.sh
git commit -m "Add chat-with-your-data pipeline and POST /api/chat

Extracts _retrieve_for_message() out of refine() so chat() reuses the exact
same Inflectiv/Postgres retrieval chart generation already uses. Chat asks
for a written answer (ChatAnswer: answer + optional attached ChartSpec)
instead of forcing everything into a chart. Gated by the same readiness
guardrail as generate/refine.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push origin dev
```

---

### Task 5: Make the signup wizard's data-source step optional

**Files:**
- Modify: `frontend/Agentic Auth.dc.html`

**Interfaces:**
- Consumes: nothing new — this only changes an existing client-side gate function.
- Produces: nothing new — `canStep()`'s existing signature and call sites are unchanged.

- [ ] **Step 1: Make step index 2 (data sources) always advance**

In `frontend/Agentic Auth.dc.html`, `canStep()` currently reads:
```javascript
  canStep() {
    const s = this.state.su, st = this.state.step;
    if (st === 0) return !!(s.name && this.emailOk(s.email) && s.company && s.password.length >= 8 && s.terms);
    if (st === 1) return !!(s.industry && s.size && s.useCase && s.team);
    if (st === 2) {
      if (s.sourceType === 'database') return !!(s.connString.trim() && s.tableName.trim());
      return !!(s.inflectivKey.trim() && s.datasetId);
    }
    if (st === 3) return !!(s.goal.trim() || s.goals.length >= 1);
    return true;
  }
```
Change the `st === 2` branch to always allow advancing:
```javascript
  canStep() {
    const s = this.state.su, st = this.state.step;
    if (st === 0) return !!(s.name && this.emailOk(s.email) && s.company && s.password.length >= 8 && s.terms);
    if (st === 1) return !!(s.industry && s.size && s.useCase && s.team);
    if (st === 2) return true;
    if (st === 3) return !!(s.goal.trim() || s.goals.length >= 1);
    return true;
  }
```

- [ ] **Step 2: Add a visible "skip" hint to the data-source step**

In `frontend/Agentic Auth.dc.html`, the data-source step's source-type toggle block currently reads:
```html
        <!-- STEP 2: Data sources -->
        <sc-if value="{{ isStep2 }}" hint-placeholder-val="{{ false }}">
          <div>
            <div style="display:flex;gap:4px;background:var(--bg-inset);padding:4px;border-radius:11px;margin-bottom:16px;">
              <button onMouseDown="{{ pickInflectiv }}" style="flex:1;height:36px;border:none;border-radius:8px;background:{{ inflectivBtnBg }};color:{{ inflectivBtnFg }};font:600 13px 'Hanken Grotesk',sans-serif;cursor:pointer;box-shadow:{{ inflectivBtnShadow }};transition:all .12s;">Inflectiv Platform</button>
              <button onMouseDown="{{ pickDatabase }}" style="flex:1;height:36px;border:none;border-radius:8px;background:{{ dbBtnBg }};color:{{ dbBtnFg }};font:600 13px 'Hanken Grotesk',sans-serif;cursor:pointer;box-shadow:{{ dbBtnShadow }};transition:all .12s;">PostgreSQL Database</button>
            </div>
            <sc-if value="{{ isSuSourceInflectiv }}" hint-placeholder-val="{{ true }}">
```
Insert a hint line between the toggle block and the `isSuSourceInflectiv` block:
```html
        <!-- STEP 2: Data sources -->
        <sc-if value="{{ isStep2 }}" hint-placeholder-val="{{ false }}">
          <div>
            <div style="display:flex;gap:4px;background:var(--bg-inset);padding:4px;border-radius:11px;margin-bottom:16px;">
              <button onMouseDown="{{ pickInflectiv }}" style="flex:1;height:36px;border:none;border-radius:8px;background:{{ inflectivBtnBg }};color:{{ inflectivBtnFg }};font:600 13px 'Hanken Grotesk',sans-serif;cursor:pointer;box-shadow:{{ inflectivBtnShadow }};transition:all .12s;">Inflectiv Platform</button>
              <button onMouseDown="{{ pickDatabase }}" style="flex:1;height:36px;border:none;border-radius:8px;background:{{ dbBtnBg }};color:{{ dbBtnFg }};font:600 13px 'Hanken Grotesk',sans-serif;cursor:pointer;box-shadow:{{ dbBtnShadow }};transition:all .12s;">PostgreSQL Database</button>
            </div>
            <p style="margin:0 0 14px;font-size:12px;line-height:1.5;color:var(--ink-500);" data-testid="step2-skip-hint">You can skip this and connect a data source later from the dashboard — filling it in now just saves a step.</p>
            <sc-if value="{{ isSuSourceInflectiv }}" hint-placeholder-val="{{ true }}">
```

- [ ] **Step 3: Verify via Playwright**

Run: `cd "/Users/abdullah/Desktop/Dashboard system" && make start`

Then, using the Playwright MCP tools:
1. `mcp__plugin_playwright_playwright__browser_navigate` to `http://localhost:8000/Agentic%20Auth.dc.html`
2. `mcp__plugin_playwright_playwright__browser_snapshot` to find the Step 0 fields; fill name/email/company/password (8+ chars), check the terms checkbox, click Next.
3. On Step 1 (company info), fill industry/size/useCase/team, click Next.
4. On Step 2, take a snapshot and confirm the text "You can skip this and connect a data source later from the dashboard" is visible (`data-testid="step2-skip-hint"`), and confirm the Next button is NOT disabled (no `disabled` attribute / not styled as `var(--border-strong)`) — without typing anything into the Inflectiv key or DB connection fields, click Next.
5. Confirm the wizard advances to Step 3 ("What do you want to analyze?") — i.e., the step index changed and Step-3-specific content is now visible.

Expected: the wizard advances past Step 2 with all data-source fields left blank.

- [ ] **Step 4: Commit**

```bash
cd "/Users/abdullah/Desktop/Dashboard system"
git add "frontend/Agentic Auth.dc.html"
git commit -m "Make the signup wizard's data-source step optional

Step 2 (Inflectiv key / DB connection) no longer blocks Next — users can
finish signup and connect a data source later from the dashboard composer.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push origin dev
```

---

### Task 6: Remove the blocking Connect modal; add a persistent connect banner; handle guardrail responses in generate/refine

**Files:**
- Modify: `frontend/Agentic Dashboard AI.dc.html`

**Interfaces:**
- Consumes: `/api/generate` and `/api/refine`'s new `{status, message}` shape (Task 2).
- Produces: new state fields `connectBannerDismissed: boolean`. New render props `showConnectBanner`, `openConnectFromBanner`, `dismissConnectBanner`. Modified props `needsConnect` (now only reflects `showConnect`, never forces open), `canCloseConnect` (always `true`).

- [ ] **Step 1: Stop forcing the modal open on load**

`renderVals()`'s returned object currently starts:
```javascript
    return {
      theme: s.theme,
      needsConnect: !s.connected || s.showConnect,
      canCloseConnect: s.connected,
```
Change to:
```javascript
    return {
      theme: s.theme,
      needsConnect: s.showConnect,
      canCloseConnect: true,
```

- [ ] **Step 2: Let `closeConnect()` always close**

`closeConnect()` currently reads:
```javascript
  closeConnect() { if (this.state.connected) this.setState({ showConnect: false, connectErr: '' }); }
```
Change to:
```javascript
  closeConnect() { this.setState({ showConnect: false, connectErr: '' }); }
```

- [ ] **Step 3: Add `connectBannerDismissed` to initial state**

`state = {...}` currently includes `connKey: '', connName: '',` on its first line. Add the new field on the same line:
```javascript
    connected: false, connecting: false, connectErr: '', connKey: '', connName: '', connectBannerDismissed: false,
```

- [ ] **Step 4: Add `dismissConnectBanner()` handler**

Add near `closeConnect()`:
```javascript
  dismissConnectBanner() { this.setState({ connectBannerDismissed: true }); }
```

- [ ] **Step 5: Add banner props to `renderVals()`**

Add to the returned object, near `needsConnect`/`canCloseConnect`:
```javascript
      showConnectBanner: !s.connected && !s.connectBannerDismissed,
      openConnectFromBanner: () => this.openConnect(),
      dismissConnectBanner: () => this.dismissConnectBanner(),
```

- [ ] **Step 6: Add the banner markup**

Insert right after the top bar's closing `</div>` (the `<!-- ============ TOP BAR ============ -->` block ends right before `<!-- ============ BODY ============ -->`), i.e. immediately before the `<!-- ============ BODY ============ -->` comment:
```html
  <!-- ============ CONNECT BANNER ============ -->
  <sc-if value="{{ showConnectBanner }}" hint-placeholder-val="{{ false }}">
    <div style="flex:0 0 auto;display:flex;align-items:center;justify-content:center;gap:12px;padding:9px 16px;background:var(--violet-bg);border-bottom:1px solid var(--violet-border);" data-testid="connect-banner">
      <span style="font-size:12.5px;font-weight:600;color:var(--violet);">Connect a data source to get started — you can explore the dashboard first and connect whenever you're ready.</span>
      <button onMouseDown="{{ openConnectFromBanner }}" data-testid="connect-banner-cta" style="height:26px;padding:0 12px;border:none;border-radius:7px;background:var(--violet);color:#fff;font-family:'Hanken Grotesk',sans-serif;font-weight:600;font-size:11.5px;cursor:pointer;">Connect now</button>
      <button onMouseDown="{{ dismissConnectBanner }}" title="Dismiss" data-testid="connect-banner-dismiss" style="width:22px;height:22px;border:none;border-radius:6px;background:transparent;color:var(--violet);cursor:pointer;display:flex;align-items:center;justify-content:center;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
    </div>
  </sc-if>
```

- [ ] **Step 7: Handle guardrail responses in `generate()`**

`generate()` currently reads:
```javascript
  async generate(forced) {
    const g = (forced || this.state.goal || '').trim();
    if (!g) return;
    this.timers.forEach(clearTimeout); this.timers = [];
    if (!this.state.sessionId) { this.setState({ phase: 'thinking', goal: g, thinkSteps: [{ id: 's0', t: 'Connect a dataset first', status: 'done' }] }); return; }
    const jobId = 'job_' + this.uid();
    this.setState({ phase: 'thinking', focused: false, goal: g, thinkSteps: [] });
    const es = this.openStream(jobId);
    try {
      const res = await fetch(BACKEND + '/generate', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ session_id: this.state.sessionId, goal: g, job_id: jobId }) });
      if (!res.ok) { const ed = await res.json().catch(() => ({})); throw new Error(ed.detail || ('HTTP ' + res.status)); }
      const data = await res.json();
      const fresh = (data.drafts || []).map(spec => this.specToDraft(spec));
      this.setState(s => ({ thinkSteps: s.thinkSteps.map(x => Object.assign({}, x, { status: 'done' })), phase: 'ready', drafts: fresh.concat(s.drafts) }));
      this.scheduleSave();
      this.timers.push(setTimeout(() => this.setState(s => ({ drafts: s.drafts.map(d => Object.assign({}, d, { fresh: false })) })), 1400));
    } catch (e) {
      try { if (es) es.close(); } catch (x) {}
      this.pushStep('Generation failed: ' + (e.message || e), 'done');
      this.setState({ phase: 'ready' });
    }
  }
```
Change to:
```javascript
  async generate(forced) {
    const g = (forced || this.state.goal || '').trim();
    if (!g) return;
    this.timers.forEach(clearTimeout); this.timers = [];
    if (!this.state.sessionId) { this.setState({ phase: 'thinking', goal: g, thinkSteps: [{ id: 's0', t: 'Connect a data source first', status: 'done' }] }); return; }
    const jobId = 'job_' + this.uid();
    this.setState({ phase: 'thinking', focused: false, goal: g, thinkSteps: [] });
    const es = this.openStream(jobId);
    try {
      const res = await fetch(BACKEND + '/generate', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ session_id: this.state.sessionId, goal: g, job_id: jobId }) });
      if (!res.ok) { const ed = await res.json().catch(() => ({})); throw new Error(ed.detail || ('HTTP ' + res.status)); }
      const data = await res.json();
      if (data.status && data.status !== 'ready') {
        try { if (es) es.close(); } catch (x) {}
        this.pushStep(data.message || 'Could not generate — check your data source.', 'done');
        this.setState({ phase: 'ready' });
        return;
      }
      const fresh = (data.drafts || []).map(spec => this.specToDraft(spec));
      this.setState(s => ({ thinkSteps: s.thinkSteps.map(x => Object.assign({}, x, { status: 'done' })), phase: 'ready', drafts: fresh.concat(s.drafts) }));
      this.scheduleSave();
      this.timers.push(setTimeout(() => this.setState(s => ({ drafts: s.drafts.map(d => Object.assign({}, d, { fresh: false })) })), 1400));
    } catch (e) {
      try { if (es) es.close(); } catch (x) {}
      this.pushStep('Generation failed: ' + (e.message || e), 'done');
      this.setState({ phase: 'ready' });
    }
  }
```

- [ ] **Step 8: Handle guardrail responses in `sendFollow()`**

`sendFollow()` currently reads:
```javascript
  async sendFollow() {
    const g = this.state.followup.trim(); if (!g) return;
    this.setState({ followup: '' });
    if (!this.state.sessionId) { this.setState({ goal: g }); this.generate(g); return; }
    const jobId = 'job_' + this.uid();
    this.setState({ phase: 'thinking', goal: g, thinkSteps: [] });
    const es = this.openStream(jobId);
    try {
      const res = await fetch(BACKEND + '/refine', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ session_id: this.state.sessionId, message: g, job_id: jobId }) });
      if (!res.ok) { const ed = await res.json().catch(() => ({})); throw new Error(ed.detail || ('HTTP ' + res.status)); }
      const data = await res.json();
      const d = this.specToDraft(data.draft);
      this.setState(s => ({ thinkSteps: s.thinkSteps.map(x => Object.assign({}, x, { status: 'done' })), phase: 'ready', drafts: [d].concat(s.drafts) }));
      this.scheduleSave();
      this.timers.push(setTimeout(() => this.setState(s => ({ drafts: s.drafts.map(dd => Object.assign({}, dd, { fresh: false })) })), 1400));
    } catch (e) { try { if (es) es.close(); } catch (x) {} this.pushStep('Backend error (' + (e.message || e) + ')', 'done'); this.setState({ phase: 'ready' }); }
  }
```
Change to:
```javascript
  async sendFollow() {
    const g = this.state.followup.trim(); if (!g) return;
    this.setState({ followup: '' });
    if (!this.state.sessionId) { this.setState({ goal: g }); this.generate(g); return; }
    const jobId = 'job_' + this.uid();
    this.setState({ phase: 'thinking', goal: g, thinkSteps: [] });
    const es = this.openStream(jobId);
    try {
      const res = await fetch(BACKEND + '/refine', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ session_id: this.state.sessionId, message: g, job_id: jobId }) });
      if (!res.ok) { const ed = await res.json().catch(() => ({})); throw new Error(ed.detail || ('HTTP ' + res.status)); }
      const data = await res.json();
      if (data.status && data.status !== 'ready') {
        try { if (es) es.close(); } catch (x) {}
        this.pushStep(data.message || 'Could not refine — check your data source.', 'done');
        this.setState({ phase: 'ready' });
        return;
      }
      const d = this.specToDraft(data.draft);
      this.setState(s => ({ thinkSteps: s.thinkSteps.map(x => Object.assign({}, x, { status: 'done' })), phase: 'ready', drafts: [d].concat(s.drafts) }));
      this.scheduleSave();
      this.timers.push(setTimeout(() => this.setState(s => ({ drafts: s.drafts.map(dd => Object.assign({}, dd, { fresh: false })) })), 1400));
    } catch (e) { try { if (es) es.close(); } catch (x) {} this.pushStep('Backend error (' + (e.message || e) + ')', 'done'); this.setState({ phase: 'ready' }); }
  }
```

- [ ] **Step 9: Verify via Playwright**

Run: `make start` (if not already running)

Using Playwright MCP tools:
1. `mcp__plugin_playwright_playwright__browser_navigate` to `http://localhost:8000/Agentic%20Dashboard%20AI.dc.html` in a fresh context (no `ada-token`/`ada-conn` in localStorage — use a private/incognito-equivalent or clear localStorage first via `mcp__plugin_playwright_playwright__browser_evaluate` running `localStorage.clear()` then reload).
2. `mcp__plugin_playwright_playwright__browser_snapshot` — confirm the dashboard/canvas is visible (not obscured by a modal) and `data-testid="connect-banner"` is present with the text "Connect a data source to get started".
3. Click `data-testid="connect-banner-cta"` — confirm the Connect modal opens (dataset/DB picker visible).
4. Click the modal's close (X) button — confirm it closes (this was impossible pre-connection before this task; now it must work).
5. Click `data-testid="connect-banner-dismiss"` — confirm the banner disappears.
6. Type text into the goal input and click Generate — confirm the AI Agent Panel shows a step reading "Connect a data source first" (from the existing `!this.state.sessionId` guard) rather than crashing or hanging.

Expected: no forced modal on load; banner present and dismissible; modal closable at any time; generating without a connection shows a clear inline message.

- [ ] **Step 10: Commit**

```bash
cd "/Users/abdullah/Desktop/Dashboard system"
git add "frontend/Agentic Dashboard AI.dc.html"
git commit -m "Stop forcing the Connect modal open; add a dismissible connect banner

needsConnect now only reflects an explicitly-opened modal, never forces open
on load. Added a persistent (dismissible) banner prompting connection instead.
generate()/sendFollow() now branch on the backend's new {status, message}
guardrail responses instead of only handling network-level errors.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push origin dev
```

---

### Task 7: Composer bar (Mode + Source/Dataset popover replacing the modal) and Chat panel

This is the largest task — it retires the Connect modal entirely in favor of a persistent composer bar, and ships the Chat mode UI end to end (message list, `/api/chat` wiring, persistence). These ship together because a Mode toggle with a non-functional Chat side isn't a coherent reviewable increment.

**Files:**
- Modify: `frontend/Agentic Dashboard AI.dc.html`

**Interfaces:**
- Consumes: `POST /api/chat` (Task 4), `WorkspaceSave.chatMessages` (Task 3), the connect state machine already in place (`connKey`, `connDatasetId`, `connDatasets`, `loadDatasets()`, `doConnect()`, `connDbString`, `connDbTable`, `connDbTables`, `loadDbTables()`, `doDbConnect()`, `connSourceType`, `setSrcInflectiv()`, `setSrcDatabase()`, `connStage`, `connBack()`, `connectErr` — all unchanged, just re-wrapped).
- Produces: new state fields `composerMode: 'graphs'|'chat'`, `showSourcePopover: boolean`, `chatMessages: array`, `chatInput: string`, `chatThinking: boolean`. New methods `setComposerModeGraphs()`, `setComposerModeChat()`, `toggleSourcePopover()`, `closeSourcePopover()`, `onChatInput(e)`, `onChatKey(e)`, `sendChat()`.

- [ ] **Step 1: Delete the old Connect modal markup**

Delete the entire block from `<!-- ============ CONNECT OVERLAY ============ -->` through its closing `</sc-if>` — this is the full block starting at:
```html
  <!-- ============ CONNECT OVERLAY ============ -->
  <sc-if value="{{ needsConnect }}" hint-placeholder-val="{{ false }}">
```
and ending at the `</sc-if>` that closes it (immediately before `<!-- ============ TOP BAR ============ -->`). All of its inner content (source toggle, Inflectiv key/dataset stages, Database conn string/table stages) is being moved to Step 3 below — do not lose any of the field bindings, they're reused verbatim.

- [ ] **Step 2: Replace the initial state block**

`state = {...}` currently reads (after Task 6's `connectBannerDismissed` addition):
```javascript
  state = {
    connected: false, connecting: false, connectErr: '', connKey: '', connName: '', connectBannerDismissed: false,
    connStage: 'key', connDatasets: [], connDatasetId: '', connLoading: false, showConnect: false,
    connSourceType: 'inflectiv', connDbString: '', connDbTable: '', connDbTables: [], connDbLoading: false,
    sessionId: null, datasetId: null, datasetName: '', usedBackend: false, suggestedQueries: [], savedFlash: false,
    theme: 'light', goal: '', followup: '', focused: false,
    phase: 'idle', thinkSteps: [], dragging: false, dragDraft: null,
    sidebarOpen: true, aiOpen: true, activeNav: 'library', activeTab: 'overview',
    selected: [], newIds: [],
    drafts: [],
    widgets: []
  };
```
Replace `showConnect: false,` with `showSourcePopover: false,` and add the composer/chat fields:
```javascript
  state = {
    connected: false, connecting: false, connectErr: '', connKey: '', connName: '', connectBannerDismissed: false,
    connStage: 'key', connDatasets: [], connDatasetId: '', connLoading: false, showSourcePopover: false,
    connSourceType: 'inflectiv', connDbString: '', connDbTable: '', connDbTables: [], connDbLoading: false,
    sessionId: null, datasetId: null, datasetName: '', usedBackend: false, suggestedQueries: [], savedFlash: false,
    theme: 'light', goal: '', followup: '', focused: false,
    composerMode: 'graphs', chatMessages: [], chatInput: '', chatThinking: false,
    phase: 'idle', thinkSteps: [], dragging: false, dragDraft: null,
    sidebarOpen: true, aiOpen: true, activeNav: 'library', activeTab: 'overview',
    selected: [], newIds: [],
    drafts: [],
    widgets: []
  };
```

- [ ] **Step 3: Rebuild the command bar with Mode toggle, Source pill, and the source popover**

The `<!-- COMMAND BAR -->` block currently reads:
```html
    <!-- COMMAND BAR -->
    <div style="flex:1;display:flex;justify-content:center;min-width:0;position:relative;">
      <div style="width:100%;max-width:720px;position:relative;">
        <div style="display:flex;align-items:center;gap:10px;height:38px;padding:0 8px 0 13px;background:var(--bg-sub);border:1px solid {{ cmdBorder }};border-radius:11px;box-shadow:{{ cmdShadow }};transition:border-color .18s,box-shadow .18s;">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" style="flex:0 0 auto;color:var(--violet);"><path d="M12 3l1.7 4.3L18 9l-4.3 1.7L12 15l-1.7-4.3L6 9l4.3-1.7z" fill="currentColor"/></svg>
          <input value="{{ goal }}" onInput="{{ onGoalInput }}" onKeyDown="{{ onGoalKey }}" onFocus="{{ onGoalFocus }}" onBlur="{{ onGoalBlur }}" placeholder="Describe what you want to analyze…" style="flex:1;border:none;outline:none;background:transparent;font-family:'Hanken Grotesk',sans-serif;font-size:14px;color:var(--ink-900);min-width:0;" />
          <kbd style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--ink-400);border:1px solid var(--border);border-radius:5px;padding:2px 5px;background:var(--bg-panel);flex:0 0 auto;">⌘K</kbd>
          <button onMouseDown="{{ onGenerate }}" style-hover="{{ primaryHover }}" style="flex:0 0 auto;display:flex;align-items:center;gap:6px;height:28px;padding:0 12px;border:none;border-radius:8px;background:var(--violet);color:#fff;font-family:'Hanken Grotesk',sans-serif;font-weight:600;font-size:12.5px;cursor:pointer;box-shadow:var(--shadow-sm);">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L4.5 13H11l-1 9 8.5-11H12z" fill="currentColor" stroke="none"/></svg>
            Generate
          </button>
        </div>

        <!-- examples popover -->
        <sc-if value="{{ showExamples }}" hint-placeholder-val="{{ false }}">
          <div style="position:absolute;top:46px;left:0;right:0;background:var(--bg-panel);border:1px solid var(--border);border-radius:13px;box-shadow:var(--shadow-lg);padding:8px;z-index:60;animation:fadeUp .16s ease;">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-400);padding:6px 8px 8px;">{{ exampleHeading }}</div>
            <sc-for list="{{ examples }}" as="ex" hint-placeholder-count="5">
              <button onMouseDown="{{ ex.onPick }}" style-hover="{{ exHover }}" style="display:flex;align-items:center;gap:11px;width:100%;text-align:left;padding:9px 10px;border:none;border-radius:9px;background:transparent;cursor:pointer;color:var(--ink-700);">
                <span style="width:26px;height:26px;border-radius:7px;background:var(--violet-bg);color:var(--violet);display:flex;align-items:center;justify-content:center;flex:0 0 auto;">{{ ex.icon }}</span>
                <span style="font-size:13.5px;color:var(--ink-900);font-weight:500;">{{ ex.text }}</span>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-left:auto;color:var(--ink-400);"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
              </button>
            </sc-for>
          </div>
        </sc-if>
      </div>
    </div>
```
Replace it with:
```html
    <!-- COMMAND BAR -->
    <div style="flex:1;display:flex;justify-content:center;min-width:0;position:relative;">
      <div style="width:100%;max-width:720px;position:relative;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
          <div style="display:flex;gap:3px;background:var(--bg-inset);padding:3px;border-radius:9px;">
            <button onMouseDown="{{ setComposerModeGraphs }}" data-testid="mode-graphs" style="height:26px;padding:0 11px;border:none;border-radius:7px;background:{{ modeGraphsBg }};color:{{ modeGraphsFg }};font:600 12px 'Hanken Grotesk',sans-serif;cursor:pointer;">Graphs</button>
            <button onMouseDown="{{ setComposerModeChat }}" data-testid="mode-chat" style="height:26px;padding:0 11px;border:none;border-radius:7px;background:{{ modeChatBg }};color:{{ modeChatFg }};font:600 12px 'Hanken Grotesk',sans-serif;cursor:pointer;">Chat</button>
          </div>
          <button onMouseDown="{{ toggleSourcePopover }}" data-testid="source-pill" style="display:flex;align-items:center;gap:6px;height:26px;padding:0 10px;border:1px solid var(--border);border-radius:99px;background:var(--bg-panel);color:var(--ink-700);font:600 11.5px 'Hanken Grotesk',sans-serif;cursor:pointer;">
            <span style="width:6px;height:6px;border-radius:99px;background:{{ sourceDotColor }};"></span>{{ sourceLabel }}
          </button>
        </div>

        <sc-if value="{{ isGraphsMode }}" hint-placeholder-val="{{ true }}">
          <div style="display:flex;align-items:center;gap:10px;height:38px;padding:0 8px 0 13px;background:var(--bg-sub);border:1px solid {{ cmdBorder }};border-radius:11px;box-shadow:{{ cmdShadow }};transition:border-color .18s,box-shadow .18s;">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" style="flex:0 0 auto;color:var(--violet);"><path d="M12 3l1.7 4.3L18 9l-4.3 1.7L12 15l-1.7-4.3L6 9l4.3-1.7z" fill="currentColor"/></svg>
            <input value="{{ goal }}" onInput="{{ onGoalInput }}" onKeyDown="{{ onGoalKey }}" onFocus="{{ onGoalFocus }}" onBlur="{{ onGoalBlur }}" placeholder="Describe what you want to analyze…" style="flex:1;border:none;outline:none;background:transparent;font-family:'Hanken Grotesk',sans-serif;font-size:14px;color:var(--ink-900);min-width:0;" />
            <kbd style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--ink-400);border:1px solid var(--border);border-radius:5px;padding:2px 5px;background:var(--bg-panel);flex:0 0 auto;">⌘K</kbd>
            <button onMouseDown="{{ onGenerate }}" style-hover="{{ primaryHover }}" style="flex:0 0 auto;display:flex;align-items:center;gap:6px;height:28px;padding:0 12px;border:none;border-radius:8px;background:var(--violet);color:#fff;font-family:'Hanken Grotesk',sans-serif;font-weight:600;font-size:12.5px;cursor:pointer;box-shadow:var(--shadow-sm);">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L4.5 13H11l-1 9 8.5-11H12z" fill="currentColor" stroke="none"/></svg>
              Generate
            </button>
          </div>

          <!-- examples popover -->
          <sc-if value="{{ showExamples }}" hint-placeholder-val="{{ false }}">
            <div style="position:absolute;top:46px;left:0;right:0;background:var(--bg-panel);border:1px solid var(--border);border-radius:13px;box-shadow:var(--shadow-lg);padding:8px;z-index:60;animation:fadeUp .16s ease;">
              <div style="font-family:'IBM Plex Mono',monospace;font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-400);padding:6px 8px 8px;">{{ exampleHeading }}</div>
              <sc-for list="{{ examples }}" as="ex" hint-placeholder-count="5">
                <button onMouseDown="{{ ex.onPick }}" style-hover="{{ exHover }}" style="display:flex;align-items:center;gap:11px;width:100%;text-align:left;padding:9px 10px;border:none;border-radius:9px;background:transparent;cursor:pointer;color:var(--ink-700);">
                  <span style="width:26px;height:26px;border-radius:7px;background:var(--violet-bg);color:var(--violet);display:flex;align-items:center;justify-content:center;flex:0 0 auto;">{{ ex.icon }}</span>
                  <span style="font-size:13.5px;color:var(--ink-900);font-weight:500;">{{ ex.text }}</span>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-left:auto;color:var(--ink-400);"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
                </button>
              </sc-for>
            </div>
          </sc-if>
        </sc-if>

        <sc-if value="{{ isChatMode }}" hint-placeholder-val="{{ false }}">
          <div style="height:38px;display:flex;align-items:center;padding:0 13px;background:var(--bg-sub);border:1px solid var(--border);border-radius:11px;color:var(--ink-500);font-size:13px;">Switched to Chat — ask questions in the AI Agent panel on the right.</div>
        </sc-if>

        <!-- source popover (replaces the old full-screen Connect modal) -->
        <sc-if value="{{ showSourcePopover }}" hint-placeholder-val="{{ false }}">
          <div style="position:absolute;top:70px;left:0;width:360px;background:var(--bg-panel);border:1px solid var(--border);border-radius:13px;box-shadow:var(--shadow-lg);padding:16px;z-index:70;animation:fadeUp .16s ease;" data-testid="source-popover">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
              <span style="font-family:'Newsreader',serif;font-weight:600;font-size:15px;color:var(--ink-900);">Data source</span>
              <button onMouseDown="{{ closeSourcePopover }}" title="Close" style="width:24px;height:24px;border:1px solid var(--border);border-radius:7px;background:var(--bg-panel);color:var(--ink-500);cursor:pointer;display:flex;align-items:center;justify-content:center;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
            </div>
            <div style="display:flex;gap:4px;background:var(--bg-inset);padding:4px;border-radius:11px;margin-bottom:14px;">
              <button onMouseDown="{{ setSrcInflectiv }}" style="flex:1;height:32px;border:none;border-radius:8px;background:{{ srcInflectivBg }};color:{{ srcInflectivFg }};font:600 12.5px 'Hanken Grotesk',sans-serif;cursor:pointer;box-shadow:{{ srcInflectivShadow }};">Inflectiv</button>
              <button onMouseDown="{{ setSrcDatabase }}" style="flex:1;height:32px;border:none;border-radius:8px;background:{{ srcDatabaseBg }};color:{{ srcDatabaseFg }};font:600 12.5px 'Hanken Grotesk',sans-serif;cursor:pointer;box-shadow:{{ srcDatabaseShadow }};">PostgreSQL</button>
            </div>

            <sc-if value="{{ isSrcInflectiv }}" hint-placeholder-val="{{ true }}">
              <sc-if value="{{ connStageKey }}" hint-placeholder-val="{{ false }}">
                <div>
                  <label style="display:block;font-size:12px;font-weight:600;color:var(--ink-700);margin-bottom:6px;">Global API key</label>
                  <input value="{{ connKey }}" onInput="{{ onConnKey }}" type="password" placeholder="inf_global_…" data-testid="conn-key-input" style="width:100%;height:38px;padding:0 12px;border:1px solid var(--border);border-radius:9px;background:var(--bg-sub);font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--ink-900);outline:none;margin-bottom:12px;" />
                  <sc-if value="{{ hasConnectErr }}" hint-placeholder-val="{{ false }}">
                    <div style="margin-bottom:10px;font-size:11.5px;line-height:1.4;color:var(--rose);background:var(--rose-bg);border-radius:8px;padding:8px 10px;">{{ connectErr }}</div>
                  </sc-if>
                  <button onMouseDown="{{ loadDatasets }}" data-testid="load-datasets-btn" style-hover="{{ primaryHover }}" style="width:100%;height:40px;border:none;border-radius:10px;background:var(--violet);color:#fff;font-family:'Hanken Grotesk',sans-serif;font-weight:600;font-size:13px;cursor:pointer;">{{ loadBtnLabel }}</button>
                </div>
              </sc-if>
              <sc-if value="{{ connStageSelect }}" hint-placeholder-val="{{ false }}">
                <div>
                  <label style="display:block;font-size:12px;font-weight:600;color:var(--ink-700);margin-bottom:6px;">Choose a dataset</label>
                  <select value="{{ connDatasetId }}" onChange="{{ onConnDataset }}" data-testid="dataset-select" style="width:100%;height:38px;padding:0 12px;border:1px solid var(--border);border-radius:9px;background:var(--bg-sub);font-family:'Hanken Grotesk',sans-serif;font-size:13px;color:var(--ink-900);outline:none;margin-bottom:12px;cursor:pointer;">
                    <sc-for list="{{ connDatasetOptions }}" as="opt" hint-placeholder-count="3">
                      <option value="{{ opt.value }}">{{ opt.label }}</option>
                    </sc-for>
                  </select>
                  <sc-if value="{{ hasConnectErr }}" hint-placeholder-val="{{ false }}">
                    <div style="margin-bottom:10px;font-size:11.5px;line-height:1.4;color:var(--rose);background:var(--rose-bg);border-radius:8px;padding:8px 10px;">{{ connectErr }}</div>
                  </sc-if>
                  <button onMouseDown="{{ doConnect }}" data-testid="connect-dataset-btn" style-hover="{{ primaryHover }}" style="width:100%;height:40px;border:none;border-radius:10px;background:var(--violet);color:#fff;font-family:'Hanken Grotesk',sans-serif;font-weight:600;font-size:13px;cursor:pointer;">{{ connectBtnLabel }}</button>
                  <button onMouseDown="{{ connBack }}" style="width:100%;height:34px;margin-top:6px;border:none;border-radius:9px;background:transparent;color:var(--ink-500);font-family:'Hanken Grotesk',sans-serif;font-weight:600;font-size:12px;cursor:pointer;">← Use a different key</button>
                </div>
              </sc-if>
            </sc-if>

            <sc-if value="{{ isSrcDatabase }}" hint-placeholder-val="{{ false }}">
              <div>
                <label style="display:block;font-size:12px;font-weight:600;color:var(--ink-700);margin-bottom:6px;">PostgreSQL connection string</label>
                <input value="{{ connDbString }}" onInput="{{ onConnDbString }}" type="password" placeholder="postgresql://user:pass@host:5432/dbname" data-testid="conn-db-input" style="width:100%;height:38px;padding:0 12px;border:1px solid var(--border);border-radius:9px;background:var(--bg-sub);font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:var(--ink-900);outline:none;margin-bottom:12px;" />
                <sc-if value="{{ hasConnectErr }}" hint-placeholder-val="{{ false }}">
                  <div style="margin-bottom:10px;font-size:11.5px;line-height:1.4;color:var(--rose);background:var(--rose-bg);border-radius:8px;padding:8px 10px;">{{ connectErr }}</div>
                </sc-if>
                <button onMouseDown="{{ loadDbTables }}" data-testid="load-tables-btn" style-hover="{{ primaryHover }}" style="width:100%;height:40px;border:none;border-radius:10px;background:var(--violet);color:#fff;font-family:'Hanken Grotesk',sans-serif;font-weight:600;font-size:13px;cursor:pointer;">{{ loadDbTablesLabel }}</button>
                <sc-if value="{{ hasDbTables }}" hint-placeholder-val="{{ false }}">
                  <div style="margin-top:12px;">
                    <label style="display:block;font-size:12px;font-weight:600;color:var(--ink-700);margin-bottom:6px;">Choose a table</label>
                    <select value="{{ connDbTable }}" onChange="{{ onConnDbTable }}" data-testid="table-select" style="width:100%;height:38px;padding:0 12px;border:1px solid var(--border);border-radius:9px;background:var(--bg-sub);font-family:'Hanken Grotesk',sans-serif;font-size:13px;color:var(--ink-900);outline:none;margin-bottom:12px;cursor:pointer;">
                      <sc-for list="{{ connDbTableOptions }}" as="opt" hint-placeholder-count="3">
                        <option value="{{ opt.value }}">{{ opt.label }}</option>
                      </sc-for>
                    </select>
                    <button onMouseDown="{{ doDbConnect }}" data-testid="connect-table-btn" style-hover="{{ primaryHover }}" style="width:100%;height:40px;border:none;border-radius:10px;background:var(--violet);color:#fff;font-family:'Hanken Grotesk',sans-serif;font-weight:600;font-size:13px;cursor:pointer;">{{ connectDbBtnLabel }}</button>
                  </div>
                </sc-if>
              </div>
            </sc-if>
          </div>
        </sc-if>
      </div>
    </div>
```

- [ ] **Step 4: Repoint the sidebar and AI-panel "change data source" buttons**

The left sidebar's workspace switcher button currently reads:
```html
          <button onMouseDown="{{ openConnect }}" title="Change data source" style-hover="{{ wsHover }}" style="width:100%;display:flex;align-items:center;gap:10px;padding:8px 10px;border:1px solid var(--border);border-radius:10px;background:var(--bg-panel);cursor:pointer;box-shadow:var(--shadow-sm);">
```
Change `onMouseDown="{{ openConnect }}"` to `onMouseDown="{{ toggleSourcePopover }}"`.

The AI Agent Panel's "Change" button currently reads:
```html
            <button onMouseDown="{{ openConnect }}" style-hover="{{ iconBtnHover }}" style="height:28px;padding:0 12px;border:1px solid var(--border);border-radius:8px;background:var(--bg-panel);color:var(--ink-700);font-family:'Hanken Grotesk',sans-serif;font-weight:600;font-size:11.5px;cursor:pointer;flex:0 0 auto;">Change</button>
```
Change `onMouseDown="{{ openConnect }}"` to `onMouseDown="{{ toggleSourcePopover }}"`.

From Task 6, the banner CTA reads `onMouseDown="{{ openConnectFromBanner }}"` — leave the markup as-is; `openConnectFromBanner`'s handler is redefined in Step 6 below to call `toggleSourcePopover()` instead of the now-deleted `openConnect()`.

- [ ] **Step 5: Wrap the existing AI Agent Panel body in a Graphs-mode check, add the Chat panel**

The AI Agent Panel's content area (everything between the header's closing `</div>` at the end of the workflow-stepper block and the panel's closing `</aside>`) currently starts with the "data source" card and ends with the "agent input" block:
```html
        <div style="flex:1;overflow-y:auto;padding:14px 16px 16px;">

          <!-- data source -->
          <div style="display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid var(--border);border-radius:11px;background:var(--bg-sub);margin-bottom:14px;">
```
... (unchanged content through the drafts list) ...
```html
        </div>

        <!-- agent input -->
        <div style="padding:12px 14px;border-top:1px solid var(--border);background:var(--bg-sub);">
          <div style="display:flex;align-items:center;gap:9px;height:38px;padding:0 8px 0 12px;background:var(--bg-panel);border:1px solid var(--border);border-radius:10px;">
            <input value="{{ followup }}" onInput="{{ onFollowInput }}" onKeyDown="{{ onFollowKey }}" placeholder="Refine, ask, or steer the agent…" style="flex:1;border:none;outline:none;background:transparent;font-family:'Hanken Grotesk',sans-serif;font-size:13px;color:var(--ink-900);min-width:0;" />
            <button onMouseDown="{{ onFollowSend }}" style-hover="{{ primaryHover }}" style="width:28px;height:28px;border:none;border-radius:7px;background:var(--violet);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;flex:0 0 auto;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
          </div>
        </div>
      </aside>
    </sc-if>
```

Wrap the ENTIRE block from `<div style="flex:1;overflow-y:auto;padding:14px 16px 16px;">` through the "agent input" block's closing `</div>` (i.e., everything except the final `</aside>` and its closing `</sc-if>`) in `<sc-if value="{{ isGraphsMode }}">`, and add a sibling `<sc-if value="{{ isChatMode }}">` block right after it, before `</aside>`:

```html
        <sc-if value="{{ isGraphsMode }}" hint-placeholder-val="{{ true }}">
          <div style="flex:1;overflow-y:auto;padding:14px 16px 16px;">

            <!-- data source -->
            <div style="display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid var(--border);border-radius:11px;background:var(--bg-sub);margin-bottom:14px;">
              ... (all existing content, unchanged, through the drafts <sc-for> list) ...
          </div>

          <!-- agent input -->
          <div style="padding:12px 14px;border-top:1px solid var(--border);background:var(--bg-sub);">
            <div style="display:flex;align-items:center;gap:9px;height:38px;padding:0 8px 0 12px;background:var(--bg-panel);border:1px solid var(--border);border-radius:10px;">
              <input value="{{ followup }}" onInput="{{ onFollowInput }}" onKeyDown="{{ onFollowKey }}" placeholder="Refine, ask, or steer the agent…" style="flex:1;border:none;outline:none;background:transparent;font-family:'Hanken Grotesk',sans-serif;font-size:13px;color:var(--ink-900);min-width:0;" />
              <button onMouseDown="{{ onFollowSend }}" style-hover="{{ primaryHover }}" style="width:28px;height:28px;border:none;border-radius:7px;background:var(--violet);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;flex:0 0 auto;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
            </div>
          </div>
        </sc-if>

        <sc-if value="{{ isChatMode }}" hint-placeholder-val="{{ false }}">
          <div style="flex:1;overflow-y:auto;padding:14px 16px 16px;display:flex;flex-direction:column;gap:12px;" data-testid="chat-message-list">
            <sc-if value="{{ noChatMessages }}" hint-placeholder-val="{{ false }}">
              <div style="text-align:center;color:var(--ink-500);font-size:12.5px;padding:24px 8px;">Ask a direct question about your connected data — e.g. "number of sales in the last year".</div>
            </sc-if>
            <sc-for list="{{ chatMessages }}" as="m" hint-placeholder-count="4">
              <div style="{{ m.wrapStyle }}">
                <div style="{{ m.bubbleStyle }}">{{ m.text }}</div>
                <sc-if value="{{ m.hasChart }}" hint-placeholder-val="{{ false }}">
                  <div style="margin-top:8px;width:220px;border:1px solid var(--border);border-radius:11px;background:var(--bg-panel);padding:10px 11px;">{{ m.chartPreview }}</div>
                </sc-if>
              </div>
            </sc-for>
            <sc-if value="{{ chatThinking }}" hint-placeholder-val="{{ false }}">
              <div style="align-self:flex-start;font-size:12px;color:var(--ink-500);font-family:'IBM Plex Mono',monospace;" data-testid="chat-thinking">Thinking…</div>
            </sc-if>
          </div>
          <div style="padding:12px 14px;border-top:1px solid var(--border);background:var(--bg-sub);">
            <div style="display:flex;align-items:center;gap:9px;height:38px;padding:0 8px 0 12px;background:var(--bg-panel);border:1px solid var(--border);border-radius:10px;">
              <input value="{{ chatInput }}" onInput="{{ onChatInput }}" onKeyDown="{{ onChatKey }}" placeholder="Ask about your data…" data-testid="chat-input" style="flex:1;border:none;outline:none;background:transparent;font-family:'Hanken Grotesk',sans-serif;font-size:13px;color:var(--ink-900);min-width:0;" />
              <button onMouseDown="{{ onChatSend }}" data-testid="chat-send" style-hover="{{ primaryHover }}" style="width:28px;height:28px;border:none;border-radius:7px;background:var(--violet);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;flex:0 0 auto;"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
            </div>
          </div>
        </sc-if>
      </aside>
    </sc-if>
```

Note: the `<!-- ... unchanged content through the drafts list ... -->` placeholder above marks content you copy forward verbatim from the current file (the data-source card, activity/thinking block, and drafts `<sc-for>`) — it is not new markup to invent, it is the existing block being re-indented one level deeper inside the new `sc-if`.

- [ ] **Step 6: Replace connect-flow handler methods**

`openConnect()`/`closeConnect()` currently read:
```javascript
  openConnect() { this.setState({ showConnect: true, connStage: 'key', connectErr: '', connSourceType: 'inflectiv' }); }
  closeConnect() { this.setState({ showConnect: false, connectErr: '' }); }
```
Replace both with:
```javascript
  toggleSourcePopover() { this.setState(s => ({ showSourcePopover: !s.showSourcePopover, connStage: 'key', connectErr: '' })); }
  closeSourcePopover() { this.setState({ showSourcePopover: false, connectErr: '' }); }
```

In `doConnect()` and `doDbConnect()`, replace `showConnect: false` with `showSourcePopover: false` in both success branches:
```javascript
      this.setState({ connected: true, connecting: false, showSourcePopover: false, usedBackend: true, sessionId: data.session_id, datasetId: data.dataset_id, datasetName: data.dataset_name || '', suggestedQueries: data.suggested_queries || [], drafts: [], widgets: [], phase: 'idle', thinkSteps: [] });
```
(and the same substitution in `doDbConnect()`'s success branch, which has the analogous `showConnect: false`).

- [ ] **Step 7: Add composer/chat methods**

Add near `onFollowInput`/`sendFollow`:
```javascript
  setComposerModeGraphs() { this.setState({ composerMode: 'graphs' }); }
  setComposerModeChat() { this.setState({ composerMode: 'chat' }); }
  onChatInput(e) { this.setState({ chatInput: e.target.value }); }
  onChatKey(e) { if (e.key === 'Enter') this.sendChat(); }
  async sendChat() {
    const g = this.state.chatInput.trim();
    if (!g || this.state.chatThinking) return;
    if (!this.state.sessionId) {
      this.setState(s => ({ chatInput: '', chatMessages: s.chatMessages.concat([
        { id: this.uid(), role: 'user', text: g },
        { id: this.uid(), role: 'assistant', text: 'Connect a data source to get started.' }
      ]) }));
      return;
    }
    this.setState(s => ({ chatInput: '', chatThinking: true, chatMessages: s.chatMessages.concat([{ id: this.uid(), role: 'user', text: g }]) }));
    try {
      const res = await fetch(BACKEND + '/chat', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ session_id: this.state.sessionId, message: g }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || ('HTTP ' + res.status));
      const ready = data.status === 'ready';
      const text = ready ? data.answer : (data.message || 'Could not answer — check your data source.');
      this.setState(s => ({ chatThinking: false, chatMessages: s.chatMessages.concat([{ id: this.uid(), role: 'assistant', text: text, chart: ready ? data.chart : null }]) }));
      this.scheduleSave();
    } catch (e) {
      this.setState(s => ({ chatThinking: false, chatMessages: s.chatMessages.concat([{ id: this.uid(), role: 'assistant', text: 'Error: ' + (e.message || e) }]) }));
    }
  }
```

- [ ] **Step 8: Persist and restore `chatMessages`**

`persistWorkspace()` currently reads:
```javascript
  persistWorkspace() {
    const body = { widgets: this.state.widgets, drafts: this.state.drafts };
```
Change to:
```javascript
  persistWorkspace() {
    const body = { widgets: this.state.widgets, drafts: this.state.drafts, chatMessages: this.state.chatMessages };
```

`restoreWorkspace()` currently reads:
```javascript
    if (ws && ((ws.widgets || []).length || (ws.drafts || []).length)) {
      this.setState({
        widgets: (ws.widgets || []).map(w => Object.assign({}, w, { id: w.id || this.uid() })),
        drafts: (ws.drafts || []),
        phase: (ws.drafts || []).length ? 'ready' : this.state.phase
      });
    }
```
Change to:
```javascript
    if (ws && ((ws.widgets || []).length || (ws.drafts || []).length || (ws.chatMessages || []).length)) {
      this.setState({
        widgets: (ws.widgets || []).map(w => Object.assign({}, w, { id: w.id || this.uid() })),
        drafts: (ws.drafts || []),
        chatMessages: (ws.chatMessages || []),
        phase: (ws.drafts || []).length ? 'ready' : this.state.phase
      });
    }
```

- [ ] **Step 9: Wire everything into `renderVals()`**

In the `renderVals()` method body (before the final `return {...}`), add the chat message mapping right after the existing `thinkSteps`/`workflow` computations:
```javascript
    const chatMessages = s.chatMessages.map(m => ({
      id: m.id,
      text: m.text,
      wrapStyle: 'display:flex;flex-direction:column;align-items:' + (m.role === 'user' ? 'flex-end' : 'flex-start') + ';',
      bubbleStyle: 'max-width:88%;padding:9px 12px;border-radius:12px;font-size:13px;line-height:1.45;' + (m.role === 'user' ? 'background:var(--violet);color:#fff;' : 'background:var(--bg-inset);color:var(--ink-900);'),
      hasChart: !!m.chart,
      chartPreview: m.chart ? this.buildPreview(m.chart, true) : null
    }));
```

In the returned object, replace:
```javascript
      needsConnect: s.showConnect,
      canCloseConnect: true,
      connStageKey: s.connStage === 'key',
      connStageSelect: s.connStage === 'select',
      connecting: s.connecting,
      connLoading: s.connLoading,
      connectErr: s.connectErr,
      hasConnectErr: !!s.connectErr,
      connKey: s.connKey,
      connDatasetId: s.connDatasetId,
      connDatasetOptions: s.connDatasets.map(d => ({ value: String(d.id), label: d.name + (d.knowledge_source_count ? ' · ' + d.knowledge_source_count + ' sources' : '') })),
      loadBtnLabel: s.connLoading ? 'Loading…' : 'Load my datasets',
      connectBtnLabel: s.connecting ? 'Connecting…' : 'Connect dataset',
      onConnKey: (e) => this.onConnKey(e),
      onConnDataset: (e) => this.onConnDataset(e),
      loadDatasets: () => this.loadDatasets(),
      doConnect: () => this.doConnect(),
      connBack: () => this.connBack(),
      openConnect: () => this.openConnect(),
      closeConnect: () => this.closeConnect(),
```
with:
```javascript
      showSourcePopover: s.showSourcePopover,
      toggleSourcePopover: () => this.toggleSourcePopover(),
      closeSourcePopover: () => this.closeSourcePopover(),
      connStageKey: s.connStage === 'key',
      connStageSelect: s.connStage === 'select',
      connecting: s.connecting,
      connLoading: s.connLoading,
      connectErr: s.connectErr,
      hasConnectErr: !!s.connectErr,
      connKey: s.connKey,
      connDatasetId: s.connDatasetId,
      connDatasetOptions: s.connDatasets.map(d => ({ value: String(d.id), label: d.name + (d.knowledge_source_count ? ' · ' + d.knowledge_source_count + ' sources' : '') })),
      loadBtnLabel: s.connLoading ? 'Loading…' : 'Load my datasets',
      connectBtnLabel: s.connecting ? 'Connecting…' : 'Connect dataset',
      onConnKey: (e) => this.onConnKey(e),
      onConnDataset: (e) => this.onConnDataset(e),
      loadDatasets: () => this.loadDatasets(),
      doConnect: () => this.doConnect(),
      connBack: () => this.connBack(),
```

Also update the banner props added in Task 6 — replace:
```javascript
      openConnectFromBanner: () => this.openConnect(),
```
with:
```javascript
      openConnectFromBanner: () => this.toggleSourcePopover(),
```

And replace `sidebarOpen: s.sidebarOpen,` block area additions — add these new props anywhere in the returned object (grouped near `sidebarOpen`/`aiOpen` is fine):
```javascript
      composerMode: s.composerMode,
      isGraphsMode: s.composerMode === 'graphs',
      isChatMode: s.composerMode === 'chat',
      modeGraphsBg: s.composerMode === 'graphs' ? 'var(--bg-panel)' : 'transparent',
      modeGraphsFg: s.composerMode === 'graphs' ? 'var(--violet)' : 'var(--ink-500)',
      modeChatBg: s.composerMode === 'chat' ? 'var(--bg-panel)' : 'transparent',
      modeChatFg: s.composerMode === 'chat' ? 'var(--violet)' : 'var(--ink-500)',
      setComposerModeGraphs: () => this.setComposerModeGraphs(),
      setComposerModeChat: () => this.setComposerModeChat(),
      sourceLabel: s.connected ? (s.datasetName || 'Connected') : 'Not connected',
      sourceDotColor: s.connected ? 'var(--emerald)' : 'var(--ink-400)',
      chatMessages, chatInput: s.chatInput, chatThinking: s.chatThinking,
      noChatMessages: !s.chatMessages.length,
      onChatInput: (e) => this.onChatInput(e), onChatKey: (e) => this.onChatKey(e), onChatSend: () => this.sendChat(),
```

- [ ] **Step 10: Verify via Playwright**

Run: `make start` (if not already running)

Using Playwright MCP tools, against a fresh session (clear localStorage first):
1. Navigate to `Agentic Dashboard AI.dc.html`. Snapshot — confirm `data-testid="mode-graphs"` and `data-testid="mode-chat"` and `data-testid="source-pill"` are all visible in the top bar, and confirm NO full-screen modal is present.
2. Click `data-testid="source-pill"` — confirm `data-testid="source-popover"` appears as a small anchored panel (not a full-screen overlay), containing the Inflectiv/PostgreSQL toggle.
3. Click the PostgreSQL toggle inside the popover, type a connection string into `data-testid="conn-db-input"`, click `data-testid="load-tables-btn"` — confirm this still calls `/api/db/tables` and behaves exactly as it did before (existing handler, unchanged logic).
4. Click `data-testid="mode-chat"` — confirm the AI Agent Panel now shows `data-testid="chat-message-list"` and `data-testid="chat-input"` instead of the drafts list.
5. Type a question into `data-testid="chat-input"` and click `data-testid="chat-send"` (with no session connected yet) — confirm an assistant bubble appears reading "Connect a data source to get started." (client-side guard, no network call).
6. Connect a real Postgres table via the source popover (steps 2-3), switch back to `data-testid="mode-chat"`, ask a question, click send — confirm `data-testid="chat-thinking"` appears briefly, then an assistant bubble with real answer text appears.
7. Reload the page (same logged-in session) — confirm the chat message history is still present (persistence round-trip).

Expected: composer bar fully replaces the modal; Chat mode is fully functional end-to-end; Graphs mode (generate/refine) still works unchanged.

- [ ] **Step 11: Commit**

```bash
cd "/Users/abdullah/Desktop/Dashboard system"
git add "frontend/Agentic Dashboard AI.dc.html"
git commit -m "Replace the Connect modal with a composer bar; ship Chat mode

Mode (Graphs/Chat) and Source (Inflectiv/Database + dataset) are now
dropdowns/popovers in the persistent top command bar instead of a
full-screen modal — the entire existing connect state machine (key input,
dataset picker, DB conn string, table picker) is reused verbatim, just
re-wrapped. Chat mode reuses the AI Agent Panel's real estate for a message
list wired to POST /api/chat, with messages persisted through the existing
workspace autosave.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push origin dev
```

---

### Task 8: Chart-type switching on canvas widgets

**Files:**
- Modify: `frontend/Agentic Dashboard AI.dc.html`

**Interfaces:**
- Consumes: nothing new — operates entirely on `ChartSpec` fields already present on widget objects (`type`, `data`, `series`).
- Produces: `renderType` field on widget objects (defaults to `type`, persisted in the `widgets` array via the existing `persistWorkspace()`).

- [ ] **Step 1: Add `compatibleTypes()` and `switchChartType()`**

Add near `defSpan()`:
```javascript
  compatibleTypes(spec) {
    const cur = spec.renderType || spec.type;
    const out = [];
    if (spec.data && spec.data.length) out.push('bar', 'donut', 'funnel');
    if (spec.series && spec.series.length) out.push('area', 'line', 'forecast');
    if (!out.length) return [];
    if (!out.includes(cur)) out.push(cur);
    return out;
  }
  switchChartType(id, type) {
    this.setState(s => ({ widgets: s.widgets.map(w => w.id === id ? Object.assign({}, w, { renderType: type }) : w) }));
    this.scheduleSave();
  }
```

- [ ] **Step 2: Dispatch rendering on `renderType`**

`buildPreview()` currently reads:
```javascript
  buildPreview(o, mini) {
    switch (o.type) {
```
Change to:
```javascript
  buildPreview(o, mini) {
    switch (o.renderType || o.type) {
```

- [ ] **Step 3: Compute switcher options per canvas widget**

In `renderVals()`, the `widgets = s.widgets.map(w => ({...}))` block currently reads:
```javascript
    const widgets = s.widgets.map(w => ({
      id: w.id, type: w.type,
      spanStyle: { gridColumn: 'span ' + (w.span || this.defSpan(w.type)), minHeight: (w.type === 'kpi') ? '0' : '0' },
      preview: this.buildPreview(w, false),
      cite: this.widgetCite(w),
      selected: s.selected.includes(w.id),
      borderColor: s.selected.includes(w.id) ? 'var(--violet)' : 'var(--border)',
      shadow: s.newIds.includes(w.id) ? 'var(--shadow-md)' : 'var(--shadow-sm)',
      onSelect: (e) => this.selectWidget(w.id, e),
      onDragStart: (e) => this.widgetDragStart(w.id, e),
      onRemove: (e) => { e.stopPropagation(); this.removeWidget(w.id); },
      onDup: (e) => { e.stopPropagation(); this.dupWidget(w.id); }
    }));
```
Change to:
```javascript
    const widgets = s.widgets.map(w => {
      const switchTypes = this.compatibleTypes(w).map(t => {
        const active = (w.renderType || w.type) === t;
        return {
          value: t, short: this.typeMeta(t).l.slice(0, 1), label: this.typeMeta(t).l,
          style: 'width:22px;height:22px;border-radius:6px;border:1px solid ' + (active ? 'var(--violet)' : 'var(--border)') + ';background:' + (active ? 'var(--violet-bg)' : 'var(--bg-panel)') + ';color:' + (active ? 'var(--violet)' : 'var(--ink-500)') + ';cursor:pointer;font-size:9px;font-weight:700;display:flex;align-items:center;justify-content:center;box-shadow:var(--shadow-sm);',
          onPick: () => this.switchChartType(w.id, t)
        };
      });
      return {
        id: w.id, type: w.type,
        spanStyle: { gridColumn: 'span ' + (w.span || this.defSpan(w.type)), minHeight: (w.type === 'kpi') ? '0' : '0' },
        preview: this.buildPreview(w, false),
        cite: this.widgetCite(w),
        selected: s.selected.includes(w.id),
        borderColor: s.selected.includes(w.id) ? 'var(--violet)' : 'var(--border)',
        shadow: s.newIds.includes(w.id) ? 'var(--shadow-md)' : 'var(--shadow-sm)',
        onSelect: (e) => this.selectWidget(w.id, e),
        onDragStart: (e) => this.widgetDragStart(w.id, e),
        onRemove: (e) => { e.stopPropagation(); this.removeWidget(w.id); },
        onDup: (e) => { e.stopPropagation(); this.dupWidget(w.id); },
        hasSwitcher: switchTypes.length > 1,
        switchTypes
      };
    });
```

- [ ] **Step 4: Add the switcher UI to each canvas card**

The canvas widget card template currently reads:
```html
              <div draggable="true" onDragStart="{{ w.onDragStart }}" onClick="{{ w.onSelect }}" style-hover="{{ cardHover }}" style="position:relative;height:100%;background:var(--bg-panel);border:1px solid {{ w.borderColor }};border-radius:14px;padding:15px 16px;box-shadow:{{ w.shadow }};transition:box-shadow .16s,border-color .16s,transform .12s;cursor:pointer;overflow:hidden;display:flex;flex-direction:column;">
                <div style="flex:1;min-height:0;display:flex;flex-direction:column;">{{ w.preview }}</div>
                {{ w.cite }}
                <div style="position:absolute;top:9px;right:9px;display:flex;gap:3px;opacity:.4;transition:opacity .15s;" style-hover="{{ toolbarHover }}">
                  <button onClick="{{ w.onDup }}" title="Duplicate" style="width:24px;height:24px;border-radius:7px;border:1px solid var(--border);background:var(--bg-panel);color:var(--ink-500);display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:var(--shadow-sm);"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 012-2h10"/></svg></button>
                  <button onClick="{{ w.onRemove }}" title="Remove" style="width:24px;height:24px;border-radius:7px;border:1px solid var(--border);background:var(--bg-panel);color:var(--rose);display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:var(--shadow-sm);"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
                </div>
                <sc-if value="{{ w.selected }}" hint-placeholder-val="{{ false }}">
                  <div style="position:absolute;inset:0;border:2px solid var(--violet);border-radius:14px;pointer-events:none;box-shadow:0 0 0 4px var(--violet-bg);"></div>
                </sc-if>
              </div>
```
Add the switcher row right before the `sc-if value="{{ w.selected }}"` selection-outline block:
```html
              <div draggable="true" onDragStart="{{ w.onDragStart }}" onClick="{{ w.onSelect }}" style-hover="{{ cardHover }}" style="position:relative;height:100%;background:var(--bg-panel);border:1px solid {{ w.borderColor }};border-radius:14px;padding:15px 16px;box-shadow:{{ w.shadow }};transition:box-shadow .16s,border-color .16s,transform .12s;cursor:pointer;overflow:hidden;display:flex;flex-direction:column;">
                <div style="flex:1;min-height:0;display:flex;flex-direction:column;">{{ w.preview }}</div>
                {{ w.cite }}
                <div style="position:absolute;top:9px;right:9px;display:flex;gap:3px;opacity:.4;transition:opacity .15s;" style-hover="{{ toolbarHover }}">
                  <button onClick="{{ w.onDup }}" title="Duplicate" style="width:24px;height:24px;border-radius:7px;border:1px solid var(--border);background:var(--bg-panel);color:var(--ink-500);display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:var(--shadow-sm);"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 012-2h10"/></svg></button>
                  <button onClick="{{ w.onRemove }}" title="Remove" style="width:24px;height:24px;border-radius:7px;border:1px solid var(--border);background:var(--bg-panel);color:var(--rose);display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:var(--shadow-sm);"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
                </div>
                <sc-if value="{{ w.hasSwitcher }}" hint-placeholder-val="{{ false }}">
                  <div style="position:absolute;bottom:9px;left:9px;display:flex;gap:3px;" data-testid="chart-type-switcher" onClick="{{ stopProp }}">
                    <sc-for list="{{ w.switchTypes }}" as="st" hint-placeholder-count="3">
                      <button onClick="{{ st.onPick }}" title="{{ st.label }}" data-testid="switch-to-{{ st.value }}" style="{{ st.style }}">{{ st.short }}</button>
                    </sc-for>
                  </div>
                </sc-if>
                <sc-if value="{{ w.selected }}" hint-placeholder-val="{{ false }}">
                  <div style="position:absolute;inset:0;border:2px solid var(--violet);border-radius:14px;pointer-events:none;box-shadow:0 0 0 4px var(--violet-bg);"></div>
                </sc-if>
              </div>
```
Note the `onClick="{{ stopProp }}"` on the switcher's wrapping `<div>` — this prevents a click on the switcher from bubbling up to the card's own `onClick="{{ w.onSelect }}"` (which would otherwise toggle card selection every time a switcher button is clicked). Add `stopProp: (e) => e.stopPropagation(),` to the `renderVals()` returned object, near `ghostHover`/`primaryHover`.

- [ ] **Step 5: Verify via Playwright**

Run: `make start` (if not already running)

Using Playwright MCP tools, with a Postgres source already connected (reuse the connection flow from Task 7's verification):
1. Enter a goal likely to produce a bar chart (e.g. "top selling products by quantity") and click Generate.
2. Drag a bar-chart draft onto the canvas (or use its "Add to dashboard" button).
3. Snapshot the canvas — confirm `data-testid="chart-type-switcher"` is present on that widget's card, with `data-testid="switch-to-donut"` and `data-testid="switch-to-funnel"` visible (bar/donut/funnel family, since the spec has `data[]` populated).
4. Click `data-testid="switch-to-donut"` — confirm the card's preview visually changes from a bar chart to a donut chart, and the card is NOT toggled into "selected" state by the click (confirms `stopProp` works).
5. Reload the page — confirm the widget still renders as a donut (i.e. `renderType` persisted through `persistWorkspace`/`restoreWorkspace`).
6. Add a KPI or table-type draft to the canvas — confirm `data-testid="chart-type-switcher"` is absent for that widget (fewer than 2 compatible types).

Expected: switcher appears only for compatible chart families, switches instantly with no network call, and persists across reload.

- [ ] **Step 6: Commit**

```bash
cd "/Users/abdullah/Desktop/Dashboard system"
git add "frontend/Agentic Dashboard AI.dc.html"
git commit -m "Add client-side chart-type switching for canvas widgets

Each canvas card gets a small type switcher restricted to types compatible
with whatever fields the ChartSpec already has populated: bar/donut/funnel
when data[] is present, area/line/forecast when series[] is present. Purely
a local renderType override — no backend call, no mutation of the
underlying spec data, and the choice persists through the existing
workspace autosave.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push origin dev
```

---

## After all tasks

Once Task 8 is committed, run the full smoke suite one more time end to end (`bash scripts/test_db_smoke.sh`) and do a final manual Playwright pass covering the complete story: sign up with no data source → land on dashboard with banner → connect via composer → generate charts → switch a chart's type → switch to Chat mode → ask a question → reload and confirm everything persisted. Per the project's standing git workflow rule, do **not** merge `dev` into `main` as part of this plan — that merge happens only after the user reviews and explicitly asks for it.

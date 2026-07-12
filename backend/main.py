"""Cogni Board — backend.

Holds the Inflectiv data key and LLM provider config (Fireworks / OpenRouter),
and runs the plan -> retrieve -> structure pipeline that turns a natural-language
goal into real chart components.

Run:  cd backend && uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

import agentbus
import cache
import config
import datasource
import db
import db_connector
import pipeline
import routes_app
import sessions
from auth import optional_user
from datasource import make_datasource
from guardrails import READINESS_MESSAGES, classify_readiness
from inflectiv import InflectivClient, InflectivError
from profiler import profile_dataset
from schemas import ChatRequest, DatasetsRequest, GenerateRequest, RefineRequest, SessionRequest

app = FastAPI(title="Cogni Board — backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_app.router)


@app.middleware("http")
async def no_store_frontend(request, call_next):
    """Never let the browser cache the dc-runtime files — avoids stale UI during the demo."""
    resp = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".dc.html") or path.endswith(".js"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    return resp

_DB_READY = False


@app.on_event("startup")
def _startup():
    global _DB_READY
    try:
        db.init_db()
        _DB_READY = True
    except Exception as e:
        print(f"[startup] DB unavailable ({e}); auth/persistence disabled, pipeline still works.")


@app.get("/api/health")
async def health():
    return {"ok": True, "llm": config.have_llm(), "provider": config.active_provider(),
            "db": _DB_READY, "cache": cache.backend()}


@app.get("/api/datasets")
async def list_datasets():
    """List datasets for the convenience key — used to validate setup / populate a picker."""
    key = config.INFLECTIV_FALLBACK_KEY
    if not key:
        raise HTTPException(400, "No INFLECTIV_API_KEY configured.")
    try:
        datasets = await InflectivClient(key).list_datasets()
    except InflectivError as e:
        raise HTTPException(502, str(e))
    return {"total": len(datasets), "datasets": datasets}


@app.post("/api/datasets")
async def list_datasets_for_key(req: DatasetsRequest):
    """Connect step 1: list the datasets a given global key can access, so the user
    can pick one from a dropdown. Falls back to the configured convenience key."""
    key = (req.global_key or "").strip() or config.INFLECTIV_FALLBACK_KEY
    if not key:
        raise HTTPException(400, "A global API key is required.")
    try:
        datasets = await InflectivClient(key).list_datasets()
    except InflectivError as e:
        raise HTTPException(400, str(e))
    # return a lean shape for the picker
    return {"total": len(datasets), "datasets": [
        {"id": d.get("id"), "name": d.get("name"),
         "knowledge_source_count": d.get("knowledge_source_count", 0)}
        for d in datasets
    ]}


@app.post("/api/session")
async def create_session(req: SessionRequest, user: Optional[dict] = Depends(optional_user)):
    """Connect screen / auto-connect: resolve the dataset, profile it. Supports both
    Inflectiv semantic mode and direct PostgreSQL database mode."""
    source_type = req.source_type or "inflectiv"

    if source_type == "database":
        conn_string = (req.conn_string or "").strip()
        table_name = (req.table_name or "").strip()
        if not conn_string and user and user.get("db_connection_string"):
            conn_string = user["db_connection_string"]
            if not table_name:
                table_name = user.get("db_table_name") or ""
        if not conn_string:
            raise HTTPException(400, "Database connection string is required.")
        if not table_name:
            raise HTTPException(400, "Table name is required.")

        test_result = db_connector.test_connection(conn_string)
        if not test_result.get("ok"):
            raise HTTPException(400, f"Database connection failed: {test_result.get('error')}")

        key = (req.global_key or "").strip() or config.INFLECTIV_FALLBACK_KEY
        sess = sessions.create(global_key=key, source_type="database",
                               conn_string=conn_string, table_name=table_name)
        ds = datasource.DatabaseDataSource(conn_string, table_name)
        try:
            schema = db_connector.get_table_schema(conn_string, table_name)
            sess.record_count = schema.get("row_count", 0)
        except Exception:
            pass
        profile = None
        if config.have_llm():
            try:
                profile = await ds.get_profile(emit=None)
                sess.profile = profile
            except Exception:
                pass
        return {
            "session_id": sess.session_id,
            "source_type": "database",
            "dataset_name": table_name,
            "profile": profile.model_dump() if profile else None,
            "suggested": [c.model_dump() for c in (profile.suggested_charts if profile else [])],
            "suggested_queries": (profile.suggested_queries if profile else []),
        }

    key = (req.global_key or "").strip()
    ds_id, ds_name = req.dataset_id, (req.dataset_name or "").strip() or None
    if not key and user and user.get("inflectiv_key"):
        key = user["inflectiv_key"]
        if not ds_id and not ds_name:
            ds_id = user.get("inflectiv_dataset_id")
            ds_name = user.get("inflectiv_dataset_name")
    key = key or config.INFLECTIV_FALLBACK_KEY
    if not key:
        raise HTTPException(400, "A global API key is required.")
    if not ds_id and not ds_name:
        raise HTTPException(400, "Select a dataset.")
    try:
        client = InflectivClient(key)
        if ds_id:
            dataset = await client.get_dataset_by_id(ds_id)
        else:
            dataset = await client.resolve_name_to_id(ds_name)
    except InflectivError as e:
        raise HTTPException(400, str(e))

    sess = sessions.create(key, dataset)
    profile = None
    if config.have_llm():
        try:
            profile = await profile_dataset(client, dataset)
            sess.profile = profile
        except Exception:
            pass
    return {
        "session_id": sess.session_id,
        "source_type": "inflectiv",
        "dataset_id": sess.dataset_id,
        "dataset_name": sess.dataset_name,
        "knowledge_source_count": sess.knowledge_source_count,
        "profile": profile.model_dump() if profile else None,
        "suggested": [c.model_dump() for c in (profile.suggested_charts if profile else [])],
        "suggested_queries": (profile.suggested_queries if profile else []),
    }


@app.post("/api/db/test")
async def db_test(req: SessionRequest):
    """Test a database connection."""
    conn_string = (req.conn_string or "").strip()
    if not conn_string:
        raise HTTPException(400, "Connection string is required.")
    result = db_connector.test_connection(conn_string)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Connection failed"))
    return result


@app.post("/api/db/tables")
async def db_tables(req: SessionRequest):
    """List tables for a database connection."""
    conn_string = (req.conn_string or "").strip()
    if not conn_string:
        raise HTTPException(400, "Connection string is required.")
    try:
        tables = db_connector.list_tables(conn_string)
        return {"tables": tables}
    except db_connector.DbConnectorError as e:
        raise HTTPException(400, str(e))


def _require_llm() -> None:
    if not config.have_llm():
        raise HTTPException(503, "No LLM provider configured. Set FIREWORKS_API_KEY "
                                 "(preferred) or OPENROUTER_API_KEY in backend/.env.")


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


def _persist_drafts(user_id: int, goal: str, drafts: list) -> None:
    """Auto-save generated drafts so the Components/Insights pages have real history."""
    try:
        for spec in drafts:
            db.execute(
                "INSERT INTO saved_components (user_id,spec,goal,type,dataset_name) VALUES (%s,%s,%s,%s,%s)",
                (user_id, db.Json(spec), goal, spec.get("type"), spec.get("source")))
            if spec.get("type") in ("insight", "risk", "summary"):
                db.execute(
                    "INSERT INTO saved_insights (user_id,spec,headline,tone) VALUES (%s,%s,%s,%s)",
                    (user_id, db.Json(spec), spec.get("headline") or spec.get("title"), spec.get("tone")))
        db.log_activity(user_id, "generate", goal[:120])
        db.log_activity(user_id, "credits", str(len(drafts)))  # rough credit proxy for stats
    except Exception as e:
        print(f"[persist] skipped: {e}")


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


@app.get("/api/agent/stream")
async def agent_stream(job_id: str):
    """SSE stream of live agent reasoning steps for a job_id."""
    async def gen():
        try:
            async for evt in agentbus.stream(job_id):
                yield evt
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return
    return EventSourceResponse(gen())


@app.get("/api/agent/poll")
async def agent_poll(job_id: str, since: int = 0):
    """Polling fallback for environments where SSE is awkward."""
    return agentbus.poll(job_id, since)


# --- serve the dc-runtime frontend (.dc.html, support.js, vendor/) from /frontend ---
# Mounted LAST so all /api/* routes take precedence. Single service hosts API + UI (Railway).
_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")

"""Agentic Dashboard AI — backend.

Holds the Inflectiv + OpenRouter keys and runs the plan -> retrieve -> structure
pipeline that turns a natural-language goal into real chart components.

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
import db
import pipeline
import routes_app
import sessions
from auth import optional_user
from inflectiv import InflectivClient, InflectivError
from profiler import profile_dataset
from schemas import DatasetsRequest, GenerateRequest, RefineRequest, SessionRequest

app = FastAPI(title="Agentic Dashboard AI — backend")

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
    return {"ok": True, "openrouter": config.have_openrouter(), "db": _DB_READY, "cache": cache.backend()}


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
    """Connect screen / auto-connect: resolve the dataset, profile it. The key is stored
    server-side; the browser gets back an opaque session_id. If the request omits a key
    and the caller is a logged-in user with a stored Inflectiv key, use that."""
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
    if config.have_openrouter():
        try:
            profile = await profile_dataset(client, dataset)
            sess.profile = profile
        except Exception:
            pass
    return {
        "session_id": sess.session_id,
        "dataset_id": sess.dataset_id,
        "dataset_name": sess.dataset_name,
        "knowledge_source_count": sess.knowledge_source_count,
        "profile": profile.model_dump() if profile else None,
        "suggested": [c.model_dump() for c in (profile.suggested_charts if profile else [])],
        "suggested_queries": (profile.suggested_queries if profile else []),
    }


def _require_session(session_id: str) -> sessions.Session:
    sess = sessions.get(session_id)
    if not sess:
        raise HTTPException(401, "Unknown or expired session. Reconnect on the Connect screen.")
    if not config.have_openrouter():
        raise HTTPException(503, "OPENROUTER_API_KEY is not set in backend/.env.")
    return sess


@app.post("/api/generate")
async def generate(req: GenerateRequest, user: Optional[dict] = Depends(optional_user)):
    sess = _require_session(req.session_id)
    client = InflectivClient(sess.global_key)
    emit = agentbus.make_emit(req.job_id)
    try:
        result = await pipeline.generate(
            client, sess.dataset_id, sess.dataset_name, req.goal, sess.profile, emit
        )
    except Exception as e:
        await agentbus.finish(req.job_id, 0)
        raise HTTPException(502, f"generate failed: {e}")
    await agentbus.finish(req.job_id, len(result["drafts"]))
    if user:
        _persist_drafts(user["id"], req.goal, result.get("drafts", []))
    result["job_id"] = req.job_id
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
    sess = _require_session(req.session_id)
    client = InflectivClient(sess.global_key)
    emit = agentbus.make_emit(req.job_id)
    try:
        result = await pipeline.refine(client, sess.dataset_id, sess.dataset_name, req.message, emit)
    except Exception as e:
        await agentbus.finish(req.job_id, 0)
        raise HTTPException(502, f"refine failed: {e}")
    await agentbus.finish(req.job_id, 1)
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

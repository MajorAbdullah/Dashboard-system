# Architecture

Cogni Board is a single deployable service: a **FastAPI** backend that also serves
the **`frontend/`** single-page UI. The agent turns a natural-language goal into real chart
components by retrieving from a vector/RAG store (Inflectiv) and structuring the results with
an LLM (OpenRouter), keeping a citation trail on every value.

```
Browser (frontend/*.dc.html, dc-runtime/React)
   │  relative /api calls + SSE  (+ bearer token in localStorage)
   ▼
FastAPI (backend/)
   ├─ auth + persistence  → PostgreSQL
   ├─ cache               → Redis (in-memory fallback)
   ├─ agent pipeline      → Inflectiv (RAG)  +  OpenRouter (LLM)
   └─ StaticFiles         → serves frontend/ at /
```

## The agent pipeline (`backend/pipeline.py`)

1. **Plan** — LLM turns the goal + cached dataset profile into sub-queries + a set of chart specs.
2. **Retrieve** — sub-queries hit Inflectiv (`/ext/datasets/query[/batch]`, `top_k ≤ 20`), batched, deduped, and **Redis-cached**. Broad seed queries guarantee a retrieval pool; results pool is reused when a specific query misses.
3. **Structure** — per chart, the LLM extracts the retrieved chunks into a typed **ChartSpec** (JSON), attaching the source chunks as provenance and a confidence derived from real retrieval scores. Numbers not grounded in a chunk are flagged `grounded:false` (rendered "estimated").
4. **Stream** — each step is published to an SSE channel (`/api/agent/stream`) so the UI shows live reasoning.

Connect-time **profiling** (`profiler.py`) runs once per dataset (cached): probe queries → an
LLM `DatasetProfile` with suggested KPIs/charts and **recommended natural-language queries**.

### Honesty model
The vector store returns a *sample* of text chunks, not exhaustive rows, and cannot aggregate.
So every chart value is either grounded in a cited chunk or marked estimated; provenance is
surfaced in the UI ("see sources"), and confidence reflects retrieval relevance. This is a
deliberate trust feature, not a limitation hidden from the user.

## Auth & persistence

- **Auth** (`auth.py`): sign-up/login → `sha256(salt+password)` + an opaque bearer token stored on the user row and in `localStorage`. `current_user` resolves the token on every request.
- **Per-user Inflectiv key**: captured during onboarding, stored on the user; the dashboard auto-connects via `/api/me` (no manual connect screen needed).
- **Persistence** (`db.py`, Postgres, JSONB blobs): users, dashboards, saved_components, saved_insights, activity_log, team_members, api_keys, plus a per-user `workspace` (the live canvas, auto-saved so a refresh keeps your components).
- Generated drafts are auto-persisted, so Generated Components / Saved Insights / Dashboard Library read real history.

## REST API (all under `/api`, bearer-auth unless noted)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/signup` `/auth/login` `/auth/forgot` `/auth/reset` | accounts (no auth) |
| GET / PATCH | `/me` | current user, profile + AI prefs |
| GET / PATCH | `/settings` | settings blob |
| POST | `/session` | resolve dataset + profile (uses the user's stored key if body omits one) |
| POST | `/generate` · `/refine` | run / extend the agent |
| GET | `/agent/stream` · `/agent/poll` | live reasoning steps |
| GET/POST/PUT/DELETE | `/dashboards[/{id}]` | dashboard library |
| GET/POST/PATCH/DELETE | `/components[/{id}]` | saved components |
| GET | `/insights` · `/activity` · `/stats` | history + aggregate counts |
| GET/PUT | `/workspace` | live canvas autosave |
| GET/POST/DELETE | `/team[/{id}]` · `/apikeys[/{id}]` | team + API keys |
| POST/GET | `/datasets` · GET `/my-datasets` | list datasets for a key |
| GET | `/health` | `{ok, openrouter, db, cache}` |

## Frontend (`frontend/`)

`dc-runtime` (`support.js`) compiles each `.dc.html` into a React app. Three pages:
**Auth** (sign-in / onboarding / reset), **Dashboard AI** (the builder), and **App** (the shell:
profile, datasets, generated components, saved insights, team, billing, admin, settings). The
App is auth-gated and reads real data from the API; `BACKEND` is a relative `/api` so it works
same-origin in dev and prod. React is vendored under `frontend/vendor/` (no CDN dependency).

## Notes / scope
- Pricing tiers are illustrative; there is **no payment processing** (billing shows real usage only).
- SSO buttons are visual; auth is email + password.
- The permissions matrix on Team is a capability reference.
- `docs/PROTOTYPE_NOTES.md` is the original design-prototype analysis (historical).

# Open-access onboarding, data guardrails, chat, and chart-type switching

Status: approved for implementation (dev branch)
Date: 2026-07-11

## Problem

Today the app hard-blocks users from reaching the dashboard until they attach
an Inflectiv key or a PostgreSQL connection (onboarding Step 2 won't advance,
the main app's Connect modal won't close). This is unfriendly for anyone
who wants to explore the product before they have credentials ready, and it
puts the "is there real data here" check in the wrong place — at connection
time, via a blocking form, rather than at the moment it actually matters
(chart/chat generation).

Separately, the product needs two capabilities it doesn't have yet:
a direct Q&A "chat with your data" mode (distinct from chart generation),
and the ability to change a generated chart's visual type after the fact.

## Goals

1. Remove the hard onboarding/connect gate; let users reach the app without
   a data source and connect (or skip) whenever they're ready.
2. Add a guardrail that classifies data-source readiness and blocks chart/chat
   generation with a specific, honest message when there's no real data behind
   the connection — for both Inflectiv and Postgres.
3. Add a chat mode where, with a data source connected, users can ask direct
   questions ("number of sales in the last few years") and get a direct
   answer instead of a full dashboard.
4. Let users switch a generated chart's visual type (bar/donut/line/etc.)
   after creation, constrained to types the chart's existing data can
   actually support.

## Non-goals

- No new chart types beyond the existing 12 (`kpi, area, line, bar, donut,
  funnel, heatmap, forecast, insight, risk, summary, table`).
- No server-side re-structuring of a chart's data to fit an incompatible
  type (e.g. bar → table). Type switching is a client-side reinterpretation
  of data the spec already has.
- No persistent chat history in the database — chat messages ride the
  existing workspace-autosave mechanism (same durability as saved widgets/drafts
  today: per-user via `/workspace`, or localStorage when anonymous).
- No change to how Inflectiv or Postgres are queried for chart generation —
  chat reuses those exact code paths.

## 1. Data model changes

`backend/sessions.py` — `Session` gains one field:

```python
record_count: int = 0
```

Populated at session creation (`sessions.create()`):
- Inflectiv: the existing `knowledge_source_count` value (dataset's chunk count).
- Database: `row_count` from `db_connector.get_table_schema()` — already
  fetched during profiling in `DatabaseDataSource.get_profile()`, just not
  currently threaded back onto the `Session`. `datasource.py`'s profile call
  site passes it through when constructing the session.

No new database tables. No `ChartSpec` schema changes.

## 2. Guardrail & classification pipeline (backend)

New function, e.g. in `sessions.py` or a small new `guardrails.py`:

```python
def classify_readiness(session: Optional[Session]) -> Literal[
    "not_connected", "no_source_data", "unreachable", "ready"
]:
    if session is None:
        return "not_connected"
    if session.record_count == 0:
        return "no_source_data"
    return "ready"
```

`"unreachable"` is not returned by this function directly — it's the state
the caller reports when the retrieval call itself raises (Inflectiv auth/network
error, Postgres connection failure), caught around the existing
`datasource.query()` call in `pipeline.generate()` / `pipeline.refine()` /
the new chat path.

Call sites:
- `POST /api/generate`, `POST /api/refine` (`main.py`) — replace the current
  bare `_require_session()` 401 with a call to `classify_readiness()`. On
  anything other than `"ready"`, return a 200 with a typed
  `{status: "not_connected" | "no_source_data" | "unreachable", message}`
  body (not a raw error) so the frontend can render an inline prompt instead
  of a toast/exception.
- `POST /api/chat` (new) — same gating, same response shape on failure.

This satisfies "checks whether actual data is present in both cases Inflectiv
and database" literally: `record_count` is sourced differently per
`source_type` but checked identically.

## 3. Onboarding gate removal (frontend)

**`Agentic Auth.dc.html` (signup wizard) Step 2:**
- Data-source fields (Inflectiv key/dataset, DB conn string/table) become
  optional. The "Next" button advances regardless of whether they're filled.
- Add a "Skip for now — connect later" link/button alongside the existing
  form, visually de-emphasized compared to the connect form itself.
- If the user does fill in a source, it's validated and saved to the profile
  exactly as it is today (no change to `/db/test`, `/datasets`,
  `SignupRequest` handling).

**`Agentic Dashboard AI.dc.html` (main app):**
- The Connect modal and its gating state (`needsConnect`, `canCloseConnect`)
  are removed entirely. Users land directly on the dashboard/composer view
  on load, connected or not.
- A persistent banner appears whenever `classify_readiness` would return
  `"not_connected"` (i.e., no active session): "Connect a data source to get
  started" with a button that focuses the composer's source dropdown
  (see §4). Dismissible for the session; reappears on reload while still
  disconnected.
- `restoreConnection()` keeps its existing behavior of auto-restoring a
  session from the user's saved profile fields (`inflectiv_dataset_id` /
  `db_connection_string`) — this still happens silently on load; the banner
  only shows if that restore finds nothing.

## 4. Composer bar (frontend)

Replaces the Connect modal as the single place sources are attached or
switched, modeled on the reference layout supplied during design: a
persistent bar at the bottom of the main app with inline dropdowns rather
than a separate screen.

Controls, left to right:
- **Mode**: `Graphs` | `Chat`. Explicit — this value alone decides whether
  a submitted message goes to `/api/generate`/`/api/refine` (Graphs) or the
  new `/api/chat` (Chat). No message-content classification.
- **Source**: `Inflectiv` | `Database`. Changing this reveals the relevant
  connect fields (Inflectiv key, or DB conn string + table) inline in a
  small popover anchored to the dropdown — not a full-screen modal. Submitting
  those fields calls the existing `POST /api/session` in the background and
  swaps the active `sessionId`; charts/messages already on screen are
  untouched.
- **Dataset** (Inflectiv only): sub-dropdown populated via the existing
  `POST /datasets` call, shown only when Source = Inflectiv and a key is
  already set.
- The message textbox and send button function as they do today, just now
  always visible regardless of connection state (disabled/prompting when
  disconnected, per the banner in §3).

## 5. Chat feature

**New endpoint** `POST /api/chat`:
```
Request:  { session_id: str, message: str }
Response: { answer: str, chart: ChartSpec | null, sources: SourceRef[] | null, confidence: int }
```

Gated by `classify_readiness()` exactly like generate/refine (§2).

**Database-connected sessions:**
1. Reuse the existing SQL-writer step: `chat_text(prompts.SQL_WRITER, schema + message, ...)`
   → generated SQL → `db_connector.execute_readonly()` (same 15s timeout,
   same `SELECT`-only guard as today).
2. New prompt (`prompts.CHAT_DB_ANSWERER`) turns the returned rows into a
   direct written answer. The prompt instructs the model: answer in plain
   language with the key number(s) stated explicitly; if the result is a
   trend or breakdown across more than a couple of points, additionally emit
   one `ChartSpec` (reusing the existing bar/line/area shapes) — otherwise
   `chart: null`.

**Inflectiv-connected sessions:**
1. Reuse the existing semantic search: `datasource.query()` against
   `/ext/datasets/query` / `/ext/datasets/query/batch` — the same retrieval
   Inflectiv chart generation already uses.
2. New prompt (`prompts.CHAT_INFLECTIV_ANSWERER`) synthesizes a grounded
   answer from the retrieved chunks, following the same
   confidence/`grounded`/`sources` provenance pattern `ChartSpec` already
   uses for charts. If retrieval comes back empty, the answer is an honest
   "I couldn't find that in the connected dataset" rather than a guess —
   consistent with the existing "Insufficient Data" behavior in chart
   generation.

**Frontend:** Chat mode renders a message list (user bubble + assistant
bubble). An assistant bubble with a non-null `chart` renders it inline using
the existing per-type render functions — no new renderer code. Messages are
appended to a `chatMessages` array alongside the existing `widgets`/`drafts`
arrays already autosaved via `persistWorkspace()` / `/workspace` — since
those are already untyped JSON, no `WorkspaceSave` schema change is needed.

## 6. Chart-type switching (frontend only)

Each rendered chart gets a small type-switcher (icon button group) in its
card header, offering only types compatible with the fields the `ChartSpec`
already has populated:

| Family | Types | Requires |
|---|---|---|
| Categorical | bar, donut, funnel | `data: [{label, value}]` populated |
| Series | area, line, forecast | `series: [float]` populated |
| KPI trend bonus | + area, line, forecast | KPI (`type: "kpi"`) with `series` populated |

Heatmap, table, and insight/risk/summary get no switcher — none of the other
11 types can represent grid, tabular, or prose data without server-side
re-structuring, which is explicitly out of scope (see Non-goals).

Mechanics:
- Each chart widget gets local UI state `renderType`, initialized to
  `spec.type`. The existing render dispatch (`switch (o.type)` in
  `Agentic Dashboard AI.dc.html`) switches to dispatch on `renderType`
  instead.
- Clicking a switcher option only updates `renderType` — the underlying
  `ChartSpec` object and its data fields are never mutated, so switching is
  lossless and reversible in either direction.
- `renderType` is included in the widget object when persisted to the
  workspace (`widgets` array), so the chosen presentation survives reload.
- No backend call is made when switching — this is purely a re-render.

## Error handling

- `classify_readiness()` failures return structured 200 responses (not
  exceptions) so the frontend renders an inline explanation rather than a
  generic error toast, for `/api/generate`, `/api/refine`, and `/api/chat`
  alike.
- `"unreachable"` (retrieval/connection exception at call time) is caught at
  the same point chart generation already wraps `datasource.query()` calls,
  reusing whatever try/except structure exists there today rather than adding
  a redundant pre-flight probe.
- Chat's "no data found in the connected source" case is not an error state —
  it's a normal, honest answer (`answer: "..."`, `chart: null`), matching the
  existing Inflectiv "Insufficient Data" pattern.

## Testing

- Extend `scripts/test_db_smoke.sh` with cases for: session with an empty
  table (`record_count == 0` → generate/chat should return `no_source_data`,
  not attempt SQL), and a new `/api/chat` smoke sequence (ask a count-style
  question, assert `answer` is non-empty and numeric-ish, assert `chart` is
  null for a simple scalar question).
- Manual Playwright pass on the frontend: sign up with no data source and
  confirm the dashboard loads with the banner; connect a source from the
  composer without reloading; ask a chat question; switch a bar chart to
  donut and reload to confirm `renderType` persisted.

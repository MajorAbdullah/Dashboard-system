# Cogni Board — Comprehensive Documentation

> Generated: 2026-06-14
> Scope: Full static analysis of the `Dashboard system` project directory.

---

## 0. Quick Orientation (read this first)

This project is **not** a conventional client/server web application. It is a **high‑fidelity, fully client‑side interactive prototype** of an AI‑native analytics SaaS product called **“Cogni Board.”** It is built on a small in‑browser reactive runtime (`support.js`, the **“dc‑runtime” / DataCanvas** engine) that turns each `*.dc.html` file into a live React application — with **no real backend, no database, and no real AI or payment processing.**

All data shown (datasets, KPIs, charts, team members, invoices, AI insights) is **hard‑coded mock data**. The “AI agent” is a **simulated** sequence of timed UI steps. This distinction is essential for every section below and is the basis of the blocker review in the final section.

---

## 1. System Overview

### Purpose
Cogni Board is presented as a **premium enterprise SaaS platform** that transforms raw business data (text, documents, spreadsheets, CSVs, databases, unstructured data) into **intelligent dashboards automatically** using an autonomous AI agent. The product narrative (captured in `uploads/pasted-*.txt`) is:

> “Upload data, describe your goal, let AI generate insights and dashboard components automatically, then curate the perfect dashboard from AI‑created visual assets.”

In its current implemented form, the project is the **front‑end product design / prototype** of that vision — a clickable, themeable, multi‑screen demonstration of the entire user journey.

### Primary Features (as implemented in the prototype)
- **AI command bar** — natural‑language prompt (“Describe what you want to analyze…”) that triggers a simulated agent run.
- **Simulated autonomous AI agent** — animated “thinking” steps (connect → scan rows → identify KPIs → detect anomalies → select visualizations → draft components) followed by generation of **Component Drafts**.
- **Component drafts → curation workflow** — AI output appears first as drafts in the right‑hand AI panel; the user reviews and **drags drafts onto the dashboard** (AI never auto‑commits to the dashboard).
- **Drag‑and‑drop dashboard builder** — grid of resizable widgets (KPIs, area/line/bar/donut/funnel/heatmap charts, forecasts, insights, risk alerts, tables) with select / duplicate / remove.
- **Rich data‑visualization rendering** — all charts are hand‑drawn inline SVG (sparklines, smoothed curves, donuts, bars, heatmaps, funnels, forecast bands), generated from a seeded pseudo‑random series.
- **Full authentication experience** — Sign In, multi‑step Sign‑Up/Onboarding wizard, and Forgot/Reset password flow (all client‑side validation only).
- **Application shell screens** — Profile, Settings center (12 sections), Datasets hub, Generated Components history/library, Team Workspaces, Billing & Plans, Admin Console.
- **Light/Dark theming** — CSS variable themes persisted to `localStorage`.
- **Enterprise polish** — compliance badges (SOC 2 / GDPR / HIPAA), SSO/SCIM/Okta indicators, audit‑log UI, permission matrix.

### What it is NOT (current state)
- No server, API, or persistence layer (beyond a theme preference in `localStorage`).
- No real authentication, authorization, or sessions.
- No real AI model, inference, or data ingestion.
- No real payment processing or credit metering (Billing is a visual mock).

---

## 2. System Flow

Because the system is entirely client‑side, the “system flow” is the lifecycle of a `*.dc.html` page inside the `support.js` runtime, plus the navigation between pages.

### 2.1 Boot / Runtime data flow (per page)
```
Browser loads "<Name>.dc.html"
        │
        ▼
<script src="./support.js"> executes (IIFE)
        │
        ├─ hideRawTemplate()                  → hides <x-dc> source flash
        ├─ loadReactUmd()                     → injects React 18.3.1 + ReactDOM UMD from unpkg CDN
        │      (Babel 7.26.4 from unpkg is lazy‑loaded only for x-import JSX/TS modules)
        ▼
init() runs:
        ├─ createRuntime(document)            → builds the component registry
        ├─ injects BASE_CSS + FULL_PAGE_CSS
        ├─ exposes window API (__dcBoot, DCLogic, getDC, editor bridges…)
        ▼
boot(runtime):
        ├─ parseDcDocument()                  → splits page into { template, js, props }
        │      template = innerHTML of <x-dc>
        │      js       = contents of <script data-dc-script> (a `class Component extends DCLogic`)
        ├─ evalDcLogic(js)                    → instantiates the Component logic class
        ├─ replaces <x-dc> with <div id="dc-root">
        ▼
React render loop:
        ├─ Component.renderVals()             → returns a plain "values" object (state → view data)
        ├─ compileTemplate(template)          → walks DOM, resolving:
        │        {interpolation}  → resolvePath() against renderVals output
        │        <sc-for list=…>  → list rendering
        │        <sc-if test=…>   → conditional rendering
        │        on*/style/attrs  → bound to handlers/values
        ▼
User interaction → this.setState() → subscribers notified → re-render
```

### 2.2 Process flow (the product narrative, simulated)
```
Raw Data → AI Analysis → Generated Components → History Library → User Selection → Dashboard
```
In code this maps to:
1. **Raw Data** — mock datasets (`sales_q2.csv`, Stripe, Postgres, Salesforce, …) shown in the Datasets hub.
2. **AI Analysis** — `generate()` schedules 6 timed “think” steps via `setTimeout` (no real computation).
3. **Generated Components** — `newDrafts(goal)` returns a keyword‑matched set of draft widgets (`forecast`/`churn`/`kpi`/default) prepended to the drafts list.
4. **History Library** — the “Generated Components” screen lists all drafts/components with confidence scores, favorites, filters.
5. **User Selection** — drag a draft onto the canvas; `onCanvasDrop()` → `addFromDraft()`.
6. **Dashboard** — `addFromDraft()` appends a new widget (with a fresh id and default grid span) to `state.widgets`.

### 2.3 Cross‑page navigation flow
Navigation between the three apps is **hard‑coded `window.location.href` redirects** to sibling files:
- `Agentic Auth.dc.html` → on successful sign‑in or wizard completion → `Agentic Dashboard AI.dc.html`
- `Agentic Dashboard AI.dc.html` → the dashboard builder (single page)
- `Agentic App.dc.html` → the application shell; its “Dashboards” nav item → `Agentic Dashboard AI.dc.html`
- Within `Agentic App.dc.html`, “page” routing is internal state (`state.page`) synced to the URL hash (`#profile`, `#settings`, `#billing`, …).

---

## 3. User Flow

A typical end‑to‑end journey:

1. **Landing on Auth** (`Agentic Auth.dc.html`)
   - Split‑screen Sign In page (brand story left, auth card right).
   - User enters email + password → `signinSubmit()` validates **format only** (any syntactically valid email + any non‑empty password passes) → redirect to dashboard.
   - Alternatively SSO buttons (Google / Microsoft / Slack / SSO) are present (visual only).

2. **New user → Onboarding wizard** (5 steps, gated by `canStep()`):
   - **Step 1 Account** — name, work email, company, password (≥8 chars), terms.
   - **Step 2 Company** — industry, company size, primary use case, team size.
   - **Step 3 Data Sources** — pick ≥1 integration (CSV, Excel, Google Sheets, Salesforce, HubSpot, Stripe, PostgreSQL, Snowflake, BigQuery, MySQL, API).
   - **Step 4 Goals** — free‑text goal and/or example chips (analyze revenue, forecast growth, monitor churn, detect anomalies…).
   - **Step 5 AI Setup** — dashboard style, sensitivity, insight depth, auto‑summary, forecast aggressiveness.
   - Final CTA **“Generate My First Dashboard”** → redirect to dashboard.

3. **Forgot/Reset password** (4 sub‑steps): request link → check inbox → create new password (strength meter, confirm match) → success.

4. **Dashboard builder** (`Agentic Dashboard AI.dc.html`):
   - User types a goal in the **AI command bar** (or clicks an example chip) → `generate()`.
   - Watches the **AI thinking** sequence in the right panel.
   - Reviews generated **drafts** (confidence ring, source, type, favorite).
   - **Drags** a chosen draft onto the grid canvas; widget appears, selected and highlighted.
   - Selects / duplicates / removes widgets; toggles sidebar, AI panel, and theme.

5. **Application shell** (`Agentic App.dc.html`) — user manages the rest of the product:
   - **Profile** (identity, AI preferences, productivity stats, activity timeline).
   - **Datasets** (table of sources, AI data‑health insights, suggested dashboards).
   - **Generated Components** (grid library with filters, favorites, delete).
   - **Team Workspaces** (members table, roles, shared resources, permission matrix).
   - **Billing & Plans** (current plan, pricing tiers, usage charts, invoices).
   - **Admin Console** (org stats, security events, AI governance, org controls, department usage).
   - **Settings** (12‑section center: general, workspace, AI agent, data, security, notifications, billing, API, audit, permissions, integrations, appearance).

6. **Exit** — there is no real sign‑out flow; closing the tab ends the session (only the theme preference persists).

---

## 4. Architecture

### 4.1 High‑level architecture
```
┌──────────────────────────────────────────────────────────────────────┐
│                              BROWSER                                    │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐ │
│   │  *.dc.html  (declarative app)                                    │ │
│   │   ├─ <x-dc> … </x-dc>          → template (HTML + sc-for/sc-if)  │ │
│   │   └─ <script data-dc-script>   → class Component extends DCLogic │ │
│   │         state + methods + renderVals()                          │ │
│   └────────────────────────────────────────────────────────────────┘ │
│                         ▲ parsed & driven by                           │
│   ┌────────────────────────────────────────────────────────────────┐ │
│   │  support.js  (dc-runtime, ~51 KB, generated, minified-ish)      │ │
│   │   parse · compileTemplate · resolve(expr) · walk(sc-for/sc-if)  │ │
│   │   StreamableLogic(=DCLogic) base · registry · React glue        │ │
│   └────────────────────────────────────────────────────────────────┘ │
│                         ▲ depends on (CDN)                              │
│   React 18.3.1 UMD · ReactDOM 18.3.1 UMD · Babel 7.26.4 (lazy)         │
│   Google Fonts (Newsreader, Hanken Grotesk, IBM Plex Mono)            │
└──────────────────────────────────────────────────────────────────────┘
        (no server, no API, no DB — except localStorage for theme)
```

### 4.2 Major components & interactions
- **`support.js` (the runtime / “dc‑runtime”)** — the heart of the system. Responsibilities:
  - **Parsing** (`parseDcDocument`, `parseDcText`): separates template, logic script, and `data-props`.
  - **Logic evaluation** (`evalDcLogic`): runs the `data-dc-script` with `DCLogic` (alias `StreamableLogic`) in scope; expects `class Component extends DCLogic`.
  - **Template compilation** (`compileTemplate`, `walk`, `walkFor`, `walkIf`, `walkText`, `walkElement`, `walkComponent`, `walkXImport`): converts the declarative template into React elements, resolving `{…}` interpolations via `resolve`/`resolvePath`, with `sc-for` (lists) and `sc-if` (conditionals).
  - **Reactivity**: a component registry with subscriber sets; `setState` triggers re‑render of the standalone root.
  - **Streaming/placeholder support**: shimmer placeholders and a “streaming” veil (`sc-dc-streaming`) for partially‑generated templates — a hint this runtime is the output target of an AI/editor tool.
  - **Editor bridges** (`__dcAnnotatedTemplate`, `__dcTemplateSource`, `postMessage('__dc_booted')`): designed to run inside a host editor/canvas (the DataCanvas tool).
  - **External module loading** (`walkXImport`, `loadReactUmd`, `ensureBabel`): can `x-import` JSX/TS modules, compiled in‑browser with Babel presets `["react","typescript"]`.
- **`DCLogic` (base class)** — minimal base providing `setState`, lifecycle hooks (`componentDidMount`, `componentWillUnmount`), and a default `renderVals()`. Each app subclasses it as `Component`.
- **The three apps** — independent `Component` classes, each with its own `state`, helper methods (icons via inline SVG path tables, seeded RNG chart math), and a `renderVals()` that maps state into a flat object the template binds to.
- **Inter‑app contract** — apps are linked only by **filename‑based redirects** and a shared `localStorage` key (`ada-theme`). There is no shared store.

### 4.3 Key architectural patterns
- **MV‑VM‑ish split**: template (view) + `Component` (model/logic) + `renderVals()` (view‑model projection).
- **Pure‑function rendering of data viz**: deterministic charts from `hash(id)` → seeded `rng` → `series()` → SVG path (`pts`, `smooth`). Same widget id always renders the same chart.
- **No external state management** — React‑style local state only.

---

## 5. Folder Structure

Top‑level of the project root (`Dashboard system/`):

| Path | Type | Purpose |
|------|------|---------|
| `Agentic Auth.dc.html` | App | **Authentication app** — Sign In, 5‑step Sign‑Up/Onboarding wizard, Forgot/Reset password. Entry point of the product. (~59 KB) |
| `Agentic Dashboard AI.dc.html` | App | **Dashboard builder** — AI command bar, simulated agent, draft generation, drag‑and‑drop widget grid, all chart renderers. (~85 KB) |
| `Agentic App.dc.html` | App | **Application shell** — Profile, Settings (12 sections), Datasets, Generated Components, Team, Billing, Admin. (~130 KB) |
| `Canvas.dc.html` | App (stub) | Empty `<x-dc></x-dc>` scaffold — a blank canvas/placeholder document. |
| `support.js` | Runtime | The **dc‑runtime** engine that parses, compiles, and renders every `.dc.html`. Generated from an external `dc-runtime/src/*.ts` (not included). The single most important file. (~51 KB) |
| `uploads/` | Assets / spec | User‑uploaded design brief and reference imagery. |
| `uploads/pasted-1781392618903.txt` | Spec | The **main product/design prompt** for the dashboard. |
| `uploads/pasted-1781394703706.txt` | Spec | The **remaining‑pages design prompt** (auth, onboarding, profile, settings, team, billing, datasets, components, reset, admin). |
| `uploads/pasted-1781399180861-0.png`, `…226204-0.png` | Image | Large reference mockup screenshots (~2 MB each). |
| `scraps/` | Workspace | Scratch area for the design tool. |
| `scraps/sketch-…​.napkin` | Tool file | Empty “napkin” sketch JSON (`{ "version":1, "objects":[] }`) — DataCanvas tool artifact. |
| `.thumbnail` | Tool file | Project thumbnail metadata used by the host design tool. |
| `.DS_Store` | OS | macOS Finder metadata (not part of the app). |

**Critical files to understand the system:** `support.js` (the engine) and the three `*.dc.html` apps (the screens). The `uploads/*.txt` files are the authoritative product specification.

---

## 6. Backend Overview

**There is no traditional backend.** This is a self‑contained front‑end prototype. What plays the “backend” role is the **client‑side runtime + simulated services**:

### 6.1 Technologies
- **Runtime engine:** `support.js` (“dc‑runtime”), authored in TypeScript and bundled (header: *“GENERATED from dc-runtime/src/*.ts — Rebuild with `cd dc-runtime && bun run build`”*), implying a **Bun**‑based build toolchain for the engine itself (not present in this repo).
- **UI library:** React 18.3.1 + ReactDOM 18.3.1 (UMD, from `unpkg.com`).
- **In‑browser compiler:** `@babel/standalone` 7.26.4 (from `unpkg.com`), lazy‑loaded; presets `react` + `typescript`. Used to compile `x-import`ed modules and supports TS/JSX in `data-dc-script`.
- **Language of app logic:** plain ES (the apps use `React.createElement` directly, no JSX needed).

### 6.2 Principal “modules” (within `support.js`)
| Module (source comment) | Responsibility |
|---|---|
| `src/react.ts` | `getReact`/`getReactDOM` accessors + `h` (createElement) helper. |
| `src/parse.ts` | Parse `<x-dc>` template, `data-dc-script`, and `data-props` JSON. |
| `src/boot.ts` | Boot a page: mount the standalone React root onto `#dc-root`. |
| `src/expr.ts` | Expression resolver (`resolve`, `resolvePath`, equality, paths). |
| `compileTemplate` / `walk*` | Compile template DOM → React tree; handle `sc-for`, `sc-if`, components, `x-import`. |
| `StreamableLogic` (`DCLogic`) | Base logic class: `setState`, lifecycle, `renderVals`. |
| Runtime/registry + `init` | Component registry, subscriber re‑render, `window.__dc*` API, host `postMessage` bridge, React/Babel CDN loaders. |

### 6.3 “Request handling”
There are **no HTTP request handlers**. The only network calls are:
- `loadReactUmd()` / `ensureBabel()` — fetch CDN libraries.
- `fetch(location.href)` inside `boot()` — re‑reads the page’s own source to recover the unescaped template (an editor/streaming convenience).
- `fetch(url)` inside `walkXImport` — load optional external `x-import` modules.

“Requests” a real product would make (auth, dataset ingestion, AI inference, billing) are **all simulated** with `setTimeout`, keyword matching, and static data inside the `Component` classes.

---

## 7. Frontend Overview

### 7.1 Frameworks / libraries
- **React 18.3.1** (UMD) as the rendering engine, driven indirectly through the dc‑runtime.
- **Custom declarative template language** (`sc-for`, `sc-if`, `{interpolation}`, `on*`/`style` bindings) compiled by `support.js`.
- **Inline SVG** for all data visualizations (no charting library).
- **Google Fonts**: Newsreader (display serif), Hanken Grotesk (UI sans), IBM Plex Mono (numeric/mono).
- **CSS custom properties** for the entire design system (light + dark token sets).

### 7.2 Design system (shared across all apps)
Defined in each file’s `:root` / `[data-theme="dark"]` blocks:
- Surfaces: `--bg-app`, `--bg-panel`, `--bg-sub`, `--bg-inset`; borders `--border`, `--border-strong`.
- Ink scale: `--ink-900 … --ink-400`.
- Accents: `--violet` (primary), `--emerald` (positive), `--amber` (warning), `--rose` (negative), `--teal`, `--blue`.
- Elevation: `--shadow-sm/md/lg/xl`.
- Theme toggled by setting `data-theme` and persisted via `localStorage['ada-theme']`.

### 7.3 Component / screen breakdown
Each `.dc.html` is one React `Component` (subclass of `DCLogic`). Internal “components” are produced by helper methods inside `renderVals()`:

**`Agentic Auth.dc.html`** — screens by `state.screen` (`signin` / `signup` / `reset`):
- Sign In card, SSO buttons, remember‑me, password show/hide.
- Onboarding wizard (`state.step` 0–4) with progress rail; helpers: `chip()`, `seg()`, integration cards, goal chips, style cards.
- Reset flow (`state.rstep` 0–3) with password‑strength meter (`strength()`), step dots.
- Validation: `emailOk()`, `canStep()`, `strength()`.

**`Agentic Dashboard AI.dc.html`** — single dashboard builder:
- Left sidebar (Library/Datasets/Components/Insights/Templates/Teams nav).
- Center grid canvas of widgets (`state.widgets`), drag/drop, select/duplicate/remove.
- Right AI panel: command bar, thinking steps, draft list.
- Chart renderers: `kpi`, `areaChart`, `barChart`, `donut`, `funnel`, `heatmap`, `forecast`, `insight`, `risk`, `summary`, `table`, plus `buildPreview` (mini thumbnails) and geometry helpers (`rng`, `hash`, `series`, `pts`, `pts2`, `smooth`).
- Agent simulation: `generate()`, `newDrafts()`.

**`Agentic App.dc.html`** — shell, page by `state.page`:
- Sidebar nav builders (`mkNav`, `navRow`), profile/settings nav.
- Pages: Profile, Datasets (`datasets`, `health`, `recommendations`), Generated Components (`allComps`, filters, favorites, `thumb()`), Team (`members`, `permRows`), Billing (`tiers`, `usageStats`, `invoices`), Admin (`adminStats`, `secEvents`, `governance`, `orgControls`, `deptUsage`), Settings (12 sections via `snDefs`), with segmented controls (`segEl`/`seg`), toggles (`tg`), theme cards.

### 7.4 Major front‑end workflows
- **Theme toggle** → `toggleTheme()` / `setThemeMode()` → `localStorage` + `data-theme`.
- **Routing** → state machine per app (`screen`/`step`/`page`) + hash sync (`history.replaceState`); cross‑app via `window.location.href`.
- **AI generation** → `generate()` schedules timed steps then `newDrafts()`.
- **Drag‑to‑dashboard** → HTML5 DnD (`draftDragStart` → `onCanvasOver` → `onCanvasDrop` → `addFromDraft`).
- **Form state** → controlled inputs via `setSi/setSu/setRs/setP/setS` immutable updaters.

---

## 8. Schema

There is **no database and no ORM**. The effective “schema” is the **in‑memory React state shape** of each app and the shapes of the mock data records. Documented below as TypeScript‑style interfaces (inferred from the code).

### 8.1 Auth app state (`Agentic Auth.dc.html`)
```ts
interface AuthState {
  theme: 'light' | 'dark';
  screen: 'signin' | 'signup' | 'reset';
  step: 0 | 1 | 2 | 3 | 4;     // onboarding wizard
  rstep: 0 | 1 | 2 | 3;        // reset flow

  si: { email: string; password: string; showPw: boolean; remember: boolean; error: string };

  su: {                         // sign-up / onboarding payload
    name: string; email: string; company: string; password: string; terms: boolean;
    industry: string; size: string; useCase: string; team: string;
    sources: string[];          // selected integration ids: csv, excel, gsheets, salesforce,
                                //   hubspot, stripe, postgres, snowflake, bigquery, mysql, api
    goal: string; goals: string[];
    style: 'Minimal'|'Balanced'|'Dense';
    sensitivity: 'Low'|'Medium'|'High';
    depth: 'Concise'|'Standard'|'Deep';
    autoSummary: boolean;
    forecast: 'Conservative'|'Balanced'|'Aggressive';
  };

  rs: { email: string; password: string; confirm: string };  // reset
}
```

### 8.2 Dashboard builder state (`Agentic Dashboard AI.dc.html`)
```ts
interface DashboardState {
  theme: 'light'|'dark';
  goal: string; followup: string; focused: boolean;
  phase: 'idle'|'thinking'|'ready';
  thinkSteps: { id: string; t: string; status: 'run'|'done' }[];
  dragging: boolean; dragDraft: string | null;
  sidebarOpen: boolean; aiOpen: boolean;
  activeNav: string; activeTab: string;
  selected: string[]; newIds: string[];
  drafts: Draft[];
  widgets: Widget[];
}

interface Draft {                 // AI-generated component (pre-dashboard)
  id: string; type: WidgetType; title: string;
  confidence: number;             // 0–100
  source: string;                 // e.g. 'crm.sync', 'stripe', 'sales_q2.csv'
  time: string;                   // 'just now', '2m ago'…
  fav: boolean; fresh?: boolean;
  label?: string; value?: string; delta?: string; tone?: 'pos'|'warn'|'neg';
}

interface Widget {                // committed dashboard widget
  id: string; type: WidgetType;
  label?: string; value?: string; delta?: string; tone?: 'pos'|'warn'|'neg';
  title?: string; source?: string;
  span?: number;                  // grid columns (12-col grid)
}

type WidgetType =
  'kpi'|'line'|'area'|'bar'|'donut'|'funnel'|'heatmap'|
  'forecast'|'insight'|'risk'|'summary'|'table';
```

### 8.3 Application shell state (`Agentic App.dc.html`)
```ts
interface AppState {
  theme: 'light'|'dark';
  page: 'profile'|'datasets'|'components'|'insights'|'team'|'billing'|'admin'
      | 'settings'|`settings-${string}`;
  settingsSection: string;
  compFilter: 'all'|'kpi'|'chart'|'forecast'|'summary'|'alert';
  compFavs: string[]; compDeleted: string[];

  settings: {
    wsName: string; dateFormat: string; region: string;
    twofa: boolean; sso: boolean; retention: string; density: string;
    aiSensitivity: 'Low'|'Medium'|'High'; anomaly: number; forecastConf: number;
    kpiAggr: string; verbosity: string; autoCat: boolean;
    notif: { dashboards:boolean; weekly:boolean; risk:boolean; insights:boolean; email:boolean; slack:boolean };
  };

  profile: {
    name:string; dept:string; tz:string; lang:string; ws:string;
    insightStyle:string; tone:string; conf:number; forecast:number;
  };
}
```

### 8.4 Representative mock “records” (illustrative — all hard‑coded)
```jsonc
// Dataset record (Datasets hub)
{ "name":"sales_q2.csv", "source":"CSV", "rows":"12,480", "cols":"28",
  "updated":"2m ago", "status":"Synced", "owner":"Avery Kim" }

// Team member
{ "name":"Avery Kim", "email":"avery@northwind.io", "dept":"Revenue Ops",
  "role":"Owner", "status":"Active", "last":"Online now" }

// Pricing tier (Billing)
{ "name":"Growth", "price":"$199", "per":"/mo", "current":true,
  "features":["Unlimited dashboards","500 AI analyses / month","Team collaboration","All integrations"] }

// Invoice
{ "date":"Jul 1, 2026", "id":"INV-2026-007", "amount":"$199.00" }
```
> Note: persistence is limited to one key — `localStorage['ada-theme']` (`'light' | 'dark'`). Nothing else survives a reload.

---

## 9. Essentials Checklist (to understand / run locally)

**Dependencies (all loaded at runtime from CDN — none vendored):**
- React 18.3.1 UMD — `https://unpkg.com/react@18.3.1/umd/react.production.min.js`
- ReactDOM 18.3.1 UMD — `https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js`
- Babel standalone 7.26.4 (lazy, only for `x-import`) — `https://unpkg.com/@babel/standalone@7.26.4/babel.min.js`
- Google Fonts: Newsreader, Hanken Grotesk, IBM Plex Mono

**Configuration / environment:**
- **No environment variables, no `.env`, no config files, no secrets** are required or present.
- No package manager / `package.json` / lockfile in this repo (the engine’s own build uses **Bun**, but that toolchain lives in the external `dc-runtime` project).

**To run locally:**
1. Keep all files together in one directory (the three apps + **`support.js`** + the `Canvas.dc.html` stub). Filenames **must be preserved exactly**, including spaces (e.g. `Agentic Dashboard AI.dc.html`), because cross‑page navigation uses literal `window.location.href`.
2. Serve the folder over **HTTP** (don’t open via `file://` — `fetch(location.href)` and CDN loads behave better over http). Examples:
   - `python3 -m http.server 8080`  →  open `http://localhost:8080/Agentic%20Auth.dc.html`
   - or any static server (`npx serve`, `bunx serve`, VS Code Live Server).
3. Ensure **outbound internet access** so React/Babel/fonts can load from unpkg / Google.
4. Start at `Agentic Auth.dc.html` (sign in / sign up) → it redirects to the dashboard.

**Requirements:** a modern evergreen browser (Chromium/Firefox/Safari) with JavaScript enabled. No build step is needed to run (compilation happens in the browser).

---

## 10. Deployments Checklist

### 10.1 Deployment platform
There is **no deployment configuration in the repository** (no Dockerfile, no CI, no `vercel.json`/`netlify.toml`, no server). The artifact is a set of **fully static files**, so it can be deployed to **any static host / CDN**:
- Vercel, Netlify, Cloudflare Pages, GitHub Pages, AWS S3 + CloudFront, Azure Static Web Apps, or any Nginx/Apache static root.

### 10.2 How deployment is done (recommended)
1. **No build required.** Upload the directory contents as‑is:
   - `support.js`, `Agentic Auth.dc.html`, `Agentic Dashboard AI.dc.html`, `Agentic App.dc.html`, `Canvas.dc.html` (and optionally `uploads/`).
2. Set the **default route / index** to `Agentic Auth.dc.html` (the natural entry point) or add a small `index.html` that redirects there.
3. Ensure the host serves `.html` and `.js` with correct MIME types (any standard static host does this automatically).
4. URL‑encode spaces in links if you add custom routing (`Agentic%20Auth.dc.html`).
5. Because libraries load from **unpkg** and fonts from **Google**, the deployment depends on those third‑party CDNs being reachable from the end user’s browser. For a hardened/offline‑capable deployment, **vendor** React, ReactDOM, Babel, and fonts locally and update the URLs in `support.js`.

### 10.3 Cloud configuration / env vars
- **None required.** There are no server processes, no environment variables, no secrets, no databases to provision.
- Optional hardening: set cache headers for `support.js` and fonts; add a Content‑Security‑Policy that allows `unpkg.com`, `fonts.googleapis.com`, `fonts.gstatic.com` (or self‑host and tighten CSP).

### 10.4 Rebuilding the runtime (advanced)
`support.js` is generated. To modify the engine itself you would need the external **`dc-runtime`** TypeScript source and **Bun** (`cd dc-runtime && bun run build`). That source is **not part of this repository**, so the runtime is effectively a vendored binary artifact here.

---

## 11. Payment Integration & Credit/Token System

### 11.1 Summary — IMPORTANT
**There is no real payment integration and no functional credit/token system.** Everything billing‑ and credit‑related is **UI mockup with hard‑coded values**. No Stripe SDK, no checkout, no webhooks, no metering, no enforcement exists in the code.

### 11.2 What is present (visual only)
**Billing & Plans screen** (`Agentic App.dc.html`):
- **Pricing tiers** (static `tiers` array):
  - **Starter — $49/mo** — 5 dashboards, 50 AI analyses/month, basic forecasting, CSV & Excel uploads.
  - **Growth — $199/mo** — *current plan* — unlimited dashboards, 500 AI analyses/month, team collaboration, all integrations.
  - **Enterprise — Custom** — unlimited everything, custom AI agents, SSO & audit logs, dedicated support.
  - The “current plan” is hard‑coded (`current: true` on Growth). Upgrade/Downgrade/Contact buttons have **no handlers** — they are styled but inert.
- **Usage analytics** (static `usageStats`): “AI credits consumed: 3,760 (+18%)”, “Dashboard generations: 24”, “API requests: 48.2K” — rendered as decorative bar sparklines, not measured.
- **Invoices** (static `invoices`): `INV-2026-004 … 007`, each `$199.00`, with non‑functional “download” affordances.
- **Payment methods**: described in the spec; not implemented as inputs/processing.

### 11.3 “AI credits” / token system (display‑only)
The concept of **AI credits** appears purely as **static display values**, never as an enforced balance:
- `Agentic App.dc.html` → Team stats: *“AI credits used: 62%”*; Admin stats: *“AI credits used: 84.2K (+12%)”*; department allocation bars (Revenue Ops 38%, Sales 27%, …) — all hard‑coded.
- Plan limits (“50 / 500 AI analyses per month”) are **text in the pricing cards**; nothing in the code counts analyses or blocks the simulated `generate()` when a limit is reached.
- The dashboard’s `generate()` runs unconditionally (timed simulation) — it **never checks, decrements, or gates on credits/tokens**.

### 11.4 Stripe’s role here
Stripe appears **only as a data‑source integration**, not as a payment processor:
- Onboarding integration card `{ id:'stripe', name:'Stripe', kind:'Payments' }` (select it as a data source).
- Datasets hub row `{ name:'Stripe · Payments', source:'API', rows:'84,201' }` (mock ingested data).
There is **no Stripe.js, no `@stripe/*` package, no API keys, no PaymentIntent/Checkout/Subscription code** anywhere.

### 11.5 Implication
To make billing real, a future implementation would need (none of which exists today): a backend, a payments provider integration (e.g., Stripe Checkout/Billing + webhooks), a persisted subscription/plan model, a metered usage/credit ledger keyed to the AI‑analysis action, and enforcement at `generate()` time.

---

## 12. Review — Critical Requirements, Blockers & Findings

The application **does run** as a prototype, but the following are the critical findings. Items marked **(blocker)** prevent the app from working in the stated/affected scenario.

1. **(Runtime blocker — offline/CDN) Hard dependency on third‑party CDNs.** React, ReactDOM, and Babel load from `unpkg.com` and fonts from Google at runtime. If unpkg/Google is unreachable (offline, restrictive CSP/firewall, or CDN outage), **the app fails to boot** — `boot()` throws *“window.React is not available yet.”* Mitigation: vendor these locally.

2. **(Navigation blocker) Exact filenames are load‑bearing.** Cross‑page navigation uses literal `window.location.href = 'Agentic Dashboard AI.dc.html'`. Renaming files, URL‑rewriting, or stripping spaces **breaks navigation**. All four `.dc.html` files plus `support.js` must be deployed together in the same directory.

3. **(Engine availability) `support.js` is a generated, vendored artifact.** Its source (`dc-runtime/src/*.ts`, built with Bun) is **not in this repo**, so the engine cannot be rebuilt or patched from these files alone. Treat `support.js` as a fixed binary dependency.

4. **No backend / no persistence.** Aside from the theme key in `localStorage`, nothing persists. All datasets, components, dashboards, team data, invoices reset on reload. This is expected for a prototype but blocks any real use.

5. **No real authentication (security).** `signinSubmit()` accepts **any well‑formed email + any non‑empty password** and redirects to the dashboard; SSO buttons are inert. There is no session, token, or access control — do **not** expose this as if it were secured.

6. **No real AI.** `generate()` is a `setTimeout` animation; `newDrafts()` is keyword matching over four hard‑coded sets. No model, no data analysis, no inference.

7. **No real payments or credit enforcement** (see Section 11). Billing, AI credits, and usage are decorative; nothing is charged, metered, or gated.

8. **Serve over HTTP, not `file://`.** `boot()` calls `fetch(location.href)` and loads remote scripts; opening files directly can cause fetch/CORS issues in some browsers. Use a static HTTP server.

9. **Minor:** `Canvas.dc.html` is an empty stub (renders nothing meaningful); `scraps/*.napkin` and `.thumbnail`/`.DS_Store` are tool/OS artifacts, not application code.

### Bottom line
The repository is a **complete, polished, runnable front‑end prototype/design** of an AI‑native analytics SaaS — excellent as a clickable demo and as a precise product/UX specification. To become a real product it requires the entire backend half that does not yet exist: authentication, data ingestion, an actual AI agent, persistence/database, and a real payments + credit‑metering system. The only hard *operational* blockers for running the prototype today are **CDN reachability** (#1) and **preserving filenames + serving over HTTP** (#2, #8).

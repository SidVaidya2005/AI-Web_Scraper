# Build Plan

> **Role:** The ordered plan — phases and numbered features to build, in sequence.
> **Read before starting a feature**; build one feature fully before the next.
> **Relates to:** features come from `project-overview.md`; status tracked in `progress-tracker.md`.

## Core Principle

Build the pipeline bottom-up and keep every step independently runnable and
testable: each layer (safety → fetch → clean → providers → extraction → jobs →
API → dashboard) is completed and verified with tests against fixtures/mocks
before the next layer depends on it. No layer reaches across a boundary defined in
`architecture.md`. The API and dashboard come last, once the engine they call
already works. Tests are deterministic — LLM providers are mocked, pages come from
local HTML fixtures, no live network.

---

## Phase 0 — Foundation

### 01 Project scaffold & tooling

Stand up the Python project skeleton so everything else has a home.

**Logic:**
- `pyproject.toml` with the approved dependencies (incl. `jsonschema`) and `ruff`/`pytest` config; create the `app/` package tree and `tests/` from the folder structure in `architecture.md`.
- `.gitignore` (`.env`, `__pycache__`, `.venv`, `*.pyc`, build artifacts); commit the existing `context/`, `CLAUDE.md`, and a lockfile (`uv.lock`).
- `.env.example` listing **every** documented env var with its default/limit; `README` run instructions (`uvicorn`, `uv run playwright install chromium`) and a responsible-use disclaimer.
- A minimal CI check (lint + test) wired to run on push.
- Verify: `ruff check` passes on the empty package, `pytest` collects zero failures, and CI runs green.

### 02 Config & settings

Typed settings loaded once from environment/`.env`.

**Logic:**
- `app/config.py`: `Settings` (pydantic-settings) with every variable from `code-standards.md` (incl. `MAX_RESPONSE_BYTES`, `ALLOW_PRIVATE_HOSTS`, `MAX_CONCURRENT_JOBS`, `MAX_QUEUED_JOBS`, `MAX_JOBS`, `MAX_REDIRECTS`, `SHUTDOWN_GRACE_SECONDS`, `RENDER_SETTLE_MS`, `FETCH_MAX_RETRIES`, `LLM_TIMEOUT_SECONDS`, `RESPECT_ROBOTS`, `RATE_LIMIT_PER_HOST_PER_MINUTE`, `ALLOWED_HOSTS`) and sane defaults; `get_settings()` cached dependency.
- A `@model_validator(mode="after")` enforces relationships: `MAX_CONCURRENT_JOBS <= MAX_QUEUED_JOBS <= MAX_JOBS`, and positivity of caps/timeouts — fail fast at startup.
- Verify: a test sets env vars and asserts `Settings()` reads them and applies defaults; an invalid relationship (e.g. `MAX_QUEUED_JOBS < MAX_CONCURRENT_JOBS`) raises at construction.

### 03 App skeleton + health endpoint

A runnable FastAPI app with lifespan wiring (no browser yet) and a health check.

**Logic:**
- `app/main.py` `create_app()` + lifespan that creates the `JobStore` placeholder; `TrustedHostMiddleware` with `ALLOWED_HOSTS` (Host-header allow-list — v1 DNS-rebinding baseline); a `python -m app` entry point (`app/__main__.py`) that calls `uvicorn.run(host=settings.host, port=settings.port)` so `HOST`/`PORT` are honored; `app/logging.py`; `app/api/health.py` `GET /health` (liveness only → `200`).
- Verify: TestClient hits `/health` → 200; app starts and shuts down cleanly.

---

## Phase 1 — Fetch & Render

### 04 URL safety & SSRF guard

Block server-side request forgery before any network I/O exists to abuse.

**Logic:**
- `app/fetching/url_guard.py`: `validate(url, *, settings)` (scheme allow-list + reject loopback / private / link-local / reserved / multicast / cloud-metadata `169.254.169.254` unless `ALLOW_PRIVATE_HOSTS`) **and** `resolve_and_validate(url, *, settings) -> (host, ip)` that resolves once, validates the resolved IP, and **returns it for pinning** (so the fetcher connects to the exact vetted address — closes the DNS-rebinding resolve→connect race). Re-callable on each redirect target.
- Raises a project `FetchError` (or `SSRFError` subclass) on rejection.
- Verify: public hostnames pass; `localhost`, `127.0.0.1`, `10.x`, `169.254.169.254`, `file://`, and a public host that resolves to a private IP are all rejected; `resolve_and_validate` returns the IP that gets pinned.

### 05 HTTP fetch (fast path)

Fetch raw HTML over httpx, safely and bounded.

**Logic:**
- Define a `FetchResult` (html, mode, status, content_type, final_url) — the contract must carry status/content-type/final URL so the strategy can branch (returning bare HTML loses that).
- `app/fetching/http_fetcher.py` `fetch(url, *, settings) -> FetchResult`: `resolve_and_validate` first and **connect to the pinned IP per request** — IP in the URL, `Host` header = original host (with port), `extensions={"sni_hostname": host}` so TLS verification stays on the hostname (no custom transport; see `library-docs.md`) — so the byte stream comes from the vetted address; `follow_redirects=False` with manual per-hop re-resolve+re-pin (≤ `MAX_REDIRECTS`); stream the body and cap at `MAX_RESPONSE_BYTES` *before buffering* (the hard byte guarantee); timeout + `User-Agent`.
- Verify: tests against a mock transport for success, timeout, non-2xx, oversized body (capped), too-many-redirects, a redirect to a blocked address (rejected), and a rebinding fixture where the host resolves public but the pinned connection targets the vetted IP (connection goes to the pinned IP, not a re-resolved one).

### 06 Browser render (fallback)

Render JS-heavy pages with the shared Playwright browser.

**Logic:**
- Add a lazy `BrowserManager` (in `app/fetching/browser.py`) to `app.state`: it launches one shared Chromium on the **first** `render=True` request under a lock — **not** at startup, so HTTP-only runs never need Chromium — and its `aclose()` closes it only if launched. `render(url, *, browser, settings) -> FetchResult` (called with the live browser from `await browser_manager.get()`): pre-validate the top URL; create the context with `service_workers="block"` (SW fetches bypass routes); install a `context.route` SSRF guard validating **every** HTTP request (main + redirects + sub-resources) and a `context.route_web_socket` handler that **blocks all** WebSockets for SSRF safety (can't be vetted by the http-scheme guard or IP-pinned; a non-connecting handler would dangle) — an **accepted rendering limitation**: pages that hydrate the DOM purely from a socket stream won't fully render; `wait_until="domcontentloaded"` + bounded `RENDER_SETTLE_MS` settle (**not** `networkidle`); ms timeouts.
- Return **real** metadata in the `FetchResult` from the `page.goto()` response (`status`, `content-type`) and `page.url` — never hardcode `200`/`text/html`/original URL.
- Size cap is **best-effort** (cumulative `content-length` budget + post-render backstop); the hard byte guarantee is the HTTP fast path. Document this.
- Verify: render a local fixture and assert post-JS content appears; the browser is launched **lazily** (first render only, exactly once under concurrency) and **HTTP-only usage never launches Chromium**; a blocked top URL is rejected before navigation; a blocked sub-resource/redirect/WebSocket is aborted; a SW-fetch can't reach a blocked host; an over-cap render fails; the FetchResult reflects a real non-200/redirected response.

### 07 Fetch strategy / render decision

Decide when the HTTP body is insufficient and (if opted in) render.

**Logic:**
- `app/fetching/fetch_service.py` `fetch(url, *, browser_manager, render: bool = False) -> FetchResult` (gets the live browser lazily via `browser_manager.get()` only in the render branch); `needs_render(html)` heuristic (empty/tiny body, SPA root, no visible text). Implement the **Fallback decision matrix** in `architecture.md` exactly, branching on `FetchResult.status`/`content_type`. **Rendering is opt-in:** the browser runs only when `render=True`; with `render=False` (default) an insufficient/non-HTML/non-2xx/timeout outcome becomes a job `error` (SPA-shell case hints "retry with render=true") and the browser is never launched.
- Verify: static HTML returns `mode="http"` (either flag); with `render=True` SPA-shell HTML triggers `mode="browser"`; with `render=False` SPA-shell/non-HTML/non-2xx return a job `error` and **no** browser launch; non-HTML and non-2xx follow the matrix per flag.

### 08 HTML cleaning & content reduction

Strip boilerplate and cap content to the character budget.

**Logic:**
- `app/cleaning/cleaner.py` `clean(html, *, max_chars)` using selectolax; drop `script/style/nav/footer/header/svg/iframe`; truncate to `max_content_chars` (documented lossy — no chunking in v1).
- Verify: noisy HTML in → trimmed text out, under the cap, with boilerplate gone.

---

## Phase 2 — AI Extraction

### 09 LLM provider interface

Define the provider contract and error type.

**Logic:**
- `app/providers/base.py`: `LLMProvider` protocol with `extract(*, content, prompt, json_schema) -> dict`; `ProviderError`.
- Verify: a fake provider implementing the protocol type-checks and is callable in a test.

### 10 Anthropic provider

Default provider via forced tool use.

**Logic:**
- `app/providers/anthropic_provider.py` using `AsyncAnthropic`, single forced tool with `strict: true` where the schema allows, untrusted-content system prompt + delimiter, model from settings; SDK errors → `ProviderError`.
- `app/providers/registry.py` selecting a provider from `LLM_PROVIDER` / per-request override.
- Verify: with the SDK mocked, a `tool_use` block is parsed into the result dict; an SDK error maps to `ProviderError`.

### 11 Extraction schemas

Validate output against the request's JSON Schema.

**Logic:**
- `app/extraction/schemas.py`: enforce **root `type: object`** + the supported subset (reject otherwise with 422); normalize for strict mode (`additionalProperties: false`, `required`); validate the LLM dict with a `Draft202012Validator(..., format_checker=FORMAT_CHECKER)` — **not** plain `jsonschema.validate` (which ignores `format`); no `create_model`. `app/models.py` `ExtractRequest` (`url`, `prompt`, `output_schema`, `provider`, `render: bool = False`) / `JobResponse`.
- Verify: a sample schema validates good/bad payloads; a root-non-object or out-of-subset schema is rejected at the boundary; a bad `format` value (e.g. malformed email) fails validation; a list extraction under a property key is accepted as the object envelope.

> **Built 2026-06-23 (deviation noted):** `app/models.py` ships **`ExtractRequest` only** —
> `JobResponse` is deferred to F13/F16, where `Job`/`JobStatus` exist (avoids rework on
> `from_job()` / the status enum). Subset enforcement is a **targeted denylist** (+ hard
> root-`type:object`), and the submit-time gate is wired as a Pydantic `@field_validator` on
> `ExtractRequest.output_schema` (raises `InvalidSchemaError(ValueError)` → 422 in F16). See
> `build-journal.md` → Feature 11.

### 12 Extraction engine

Orchestrate cleaned content + prompt/schema → validated structured result.

**Logic:**
- `app/extraction/engine.py` `extract(content, *, prompt, schema)`: pick provider, call `extract`, validate against the schema when present; treat page content as untrusted (delimiter/system prompt enforced by the provider).
- Verify: with a stub provider, returns a validated dict for a schema; a schema mismatch becomes a `ProviderError`/job error.

> **Built 2026-06-23 (deviation noted):** the engine **does not** pick the provider —
> the signature is `extract(content, *, prompt, schema, provider: LLMProvider)` and the
> **F14 runner injects** a ready provider (built via `registry.get_provider(settings,
> override=request.provider)`). This diverges from `architecture.md`'s data-flow snippet
> (`provider = registry.get_provider(settings)` shown inside the engine); chosen for a
> registry-free, trivially-testable engine. The engine reads no settings and never calls
> the registry. See `build-journal.md` → Feature 12.

---

## Phase 3 — Jobs & API

### 13 In-memory job store

The single source of job state.

**Logic:**
- `app/jobs/models.py` (`Job`, `JobStatus`); `app/jobs/store.py` `JobStore` with `create/get/list/mark_running/mark_done/mark_error`, `asyncio.Lock`, TTL eviction (terminal only, from `finished_at`), `MAX_JOBS` cap, newest-first listing.
- Verify: create→get round-trips; transitions set timestamps; eviction drops expired/excess **terminal** jobs but never `running` ones; list is newest-first.

### 14 Async job runner

Run the full pipeline as the error boundary.

**Logic:**
- `app/jobs/runner.py` `run_job(job_id, *, app_state)`: running → fetch → clean → extract → done; known errors → readable job error, unknown → generic message (traceback logged); never raises.
- Verify: a stubbed pipeline drives a job to `done`; an injected failure drives it to `error` without propagating; an unknown exception yields a generic (non-leaky) error message.

### 15 Job scheduler — concurrency, admission & shutdown

Bound and track background work so it can't exhaust resources or vanish.

**Logic:**
- `app/jobs/scheduler.py`: `try_reserve()` / `release()` / `submit(job_id)` and a `SchedulerShuttingDown` exception that `submit()` raises once draining has begun. Run `run_job` under a `MAX_CONCURRENT_JOBS` semaphore, holding a strong reference to each task (no fire-and-forget `create_task`).
- **Atomic admission control:** `try_reserve()` is a synchronous check-and-increment (no `await` between) capping in-flight + waiting at `MAX_QUEUED_JOBS`; over the cap it returns False and the API returns `503`/`429` with **no job created**. `release()` on terminal state, failed create, **or failed submit**. A `has_capacity()`+`await create()`+`submit()` sequence is a TOCTOU race — don't use it. (A semaphore alone is unbounded — waiting tasks and their `queued` jobs accumulate.)
- **Admission closes first on shutdown:** once draining, `try_reserve()` returns False so no job is created after shutdown begins. `submit()` only schedules an already-reserved task, so its sole realistic failure is shutdown, where it raises `SchedulerShuttingDown`; on that the API handler `release()`s the slot **and** terminalizes the just-created job via `mark_error(...)` (so it can't sit `queued` forever without a `finished_at`, or leak the slot). Catch the specific exception, not a broad `BaseException`.
- Lifespan shutdown stops intake → drains in-flight tasks within `SHUTDOWN_GRACE_SECONDS` → marks any non-terminal job `error`, **before** the browser is closed (a no-op if it was never launched).
- Verify: submissions over `MAX_QUEUED_JOBS` are rejected (not queued); **many concurrent submissions never exceed the cap** (atomic reservation, no overshoot); a reservation is released when `create()` raises; a `submit()` that fails after reserve+create releases the slot and leaves the job `error` (not `queued`); N within cap run without dropped/GC'd tasks; shutdown drains in-flight jobs, marks survivors `error`, and closes the browser only after draining.

### 16 Extract & jobs API endpoints

Expose submission and polling.

**Logic:**
- `app/api/extract.py`: `POST /extract` (`202` + `job_id` on accept; `503`/`429` when `scheduler.try_reserve()` returns False — atomic, before `create()`), `GET /jobs/{id}`, `GET /jobs`.
- Validate the request at the boundary: reject a root-non-object or out-of-subset `output_schema` with `422`.
- **Origin check on `POST /extract`** (state-changing) — reject cross-origin form/JSON posts (v1 CSRF baseline alongside the Host allow-list).
- Verify: TestClient submits a job (stubbed runner), polls it to a terminal state, lists it newest-first; an at-capacity submit returns `503`; a bad schema returns `422`.

---

## Phase 4 — Dashboard

### 17 Dashboard layout & submission form

Server-rendered shell and the submit form.

**UI:**
- `templates/base.html` (loads HTMX + `static/styles.css`), `templates/index.html` with a URL/prompt/schema form **plus a `render` checkbox (default unchecked) carrying a short local-network-risk note** (rendering opts out of IP-pinning — see Security model).

**Logic:**
- `app/dashboard/routes.py` `GET /` rendering `index.html`; a **form-handling** POST route that accepts `Form(...)` fields (including `render: bool = False`), enforces the Origin check, and calls the same job service the API uses (the HTML form is form-encoded, not JSON). Its response **re-renders the polling container with the `every 2s` trigger** so polling restarts even if it had stopped.
- Verify: `GET /` returns 200 HTML containing the form and the (unchecked) render checkbox; submitting the form creates a job (render defaulting to false when the box is absent) and the response re-arms polling.

### 18 Jobs list & live status

Live-updating jobs table via HTMX polling that stops when done and restarts on submit.

**UI:**
- `templates/_jobs_table.html` showing each job's id, status, mode, timestamps; `index.html` polls `/partials/jobs` every ~2s.

**Logic:**
- `GET /partials/jobs` rendering the partial from `JobStore.list()`; returns **HTTP `286`** once every job is terminal (and when the table is empty) so HTMX stops polling. Restart is driven by the submit response re-arming the trigger (Feature 17), not by the dead poller.
- Verify: partial returns rows for current jobs, reflects status changes, returns `286` when all jobs are terminal/empty, and polling resumes after a new submit.

### 19 Job detail & result viewer

Inspect a single job's structured result on its own page.

**UI:**
- `templates/job_detail.html` rendering the result JSON (and error, if any), autoescaped.

**Logic:**
- `GET /jobs/{id}/view` (HTML) reading from `JobStore`.
- Verify: a done job renders its result; an error job renders its message; scraped content is escaped (no HTML injection).

### 20 Result export

Download a result as JSON or CSV.

**UI:**
- Export buttons on the detail view.

**Logic:**
- `GET /jobs/{id}/export?format=json|csv` streaming a file response generated on the fly (no persistence). CSV rules are explicit: flatten a list-of-objects envelope to rows with a stable column order (union of keys); single object → one row; empty result → header only; nested values → JSON-encoded cells; **escape formula-injection** (cells leading with `= + - @` are prefixed).
- Verify: JSON export equals the stored result; CSV flattens a tabular result correctly, handles nested/empty/heterogeneous cases, and neutralizes a `=`-leading cell.

> **Built 2026-06-23 (deviation noted):** serialization lives in a **pure module**
> `app/dashboard/export.py` (route stays thin); the route returns a **plain `Response`** with a
> `Content-Disposition` attachment header, **not** a `StreamingResponse` — the result is a fully
> in-memory dict, so streaming would be theater (the "no persistence / generate on the fly" intent is
> kept). The "list-of-objects envelope" is detected as a **single key whose value is a list of dicts**;
> any other shape (incl. a single key holding a list of *scalars*) → one row. Unknown id → 404,
> existing-but-no-result → 409, bad `?format` → 422. See `build-journal.md` → Feature 20.

---

## Phase 5 — Hardening & Extras

### 21 Error handling, timeouts, retries & respectful client

Make failures graceful and bounded across the pipeline, and be a good web citizen.

**Logic:**
- Enforce fetch/render/LLM timeouts (`FETCH_TIMEOUT_SECONDS`, `RENDER_TIMEOUT_SECONDS`, `LLM_TIMEOUT_SECONDS` passed to the SDK client); one bounded retry (`FETCH_MAX_RETRIES`) on transient fetch errors; consistent `app.<area>` logging; readable job error messages (no internal leakage).
- Respectful client (lives in `app/fetching/`): honor **robots.txt** when `RESPECT_ROBOTS` (default true; config-overridable for owned sites) and enforce `RATE_LIMIT_PER_HOST_PER_MINUTE` via a per-host limiter, checked before each fetch (and on the robots.txt fetch itself, which also goes through `url_guard`).
- Verify: simulated timeouts/transient errors produce a clean job `error`, never a crash; a `robots.txt` disallow blocks the fetch; exceeding the per-host rate limit defers/rejects; logs include the area prefix.

> **Built 2026-06-23 (deviations noted):** the **timeout/retry half was already shipped** (F05 fetch
> timeout, F06 render timeout, F10 LLM timeout, F07 bounded transient retry, F14 readable errors) — F21
> **verified** those and built only the genuinely-new work: the respectful client, the deferred
> render-timeout map, and `app.fetching` logging. The respectful-client **module** is
> `app/fetching/respect.py` (`RespectfulClient`), but the **gate is invoked by the runner**
> (`await app_state.respectful_client.guard(url)` before `fetch_service.fetch`), not inside
> `fetch_service` — the runner is the sole caller, so it's the same single chokepoint while keeping
> `fetch_service`'s signature + tests untouched. Rate-limit over cap → **reject** (`RateLimitedError`,
> non-retryable); robots **fail-open** on 404/5xx/unreachable but **`SSRFError` propagates**; robots is
> fetched via `http_fetcher` directly (SSRF-guarded, no gate recursion) and parsed with stdlib
> `RobotFileParser.parse`. Robots TTL is a module constant, **no new env var**. See
> `build-journal.md` → Feature 21.

### 22 Second provider (OpenAI)

Prove the provider abstraction.

**Logic:**
- `app/providers/openai_provider.py` mirroring the forced-tool + `strict` contract and the object envelope; selectable via `LLM_PROVIDER`/per-request `provider`.
- Verify: with the SDK mocked, the same extraction returns the same result shape as Anthropic; switching providers needs no caller change.

> **Built 2026-06-24 (decisions noted):** uses the **Chat Completions** API (forced function
> calling + strict), not the Responses API. The shared untrusted-content framing was **hoisted into
> a new `app/providers/_prompts.py`** (`SYSTEM_PROMPT`/`TOOL_NAME`/`build_user_message`) so it's
> byte-identical across providers — Anthropic refactored onto it. OpenAI's tool-call `arguments` is a
> JSON **string**, so the provider `json.loads` it and guards unparseable / non-object output as
> `ProviderError`. Token param is `max_completion_tokens`. The registry **fails fast** on a missing
> `OPENAI_API_KEY`/`OPENAI_MODEL` (no default model id). Engine untouched — F11 `normalize_for_strict`
> already emits the closed schema OpenAI strict needs. See `build-journal.md` → Feature 22.

### 23 Logging, metrics & content-overflow handling

Lightweight observability and a path past the char cap.

**Logic:**
- Structured request/job logging; per-job timing (fetch ms, render ms, LLM ms) recorded on the job for the detail view. Optional: token-aware budgeting / chunk-and-merge for pages over `MAX_CONTENT_CHARS` (the documented out-of-v1 follow-up).
- Verify: a completed job exposes timing fields; logs trace a job through its lifecycle.

---

## Feature Count

| Phase | Features |
| ----- | -------- |
| Phase 0 — Foundation | 3 |
| Phase 1 — Fetch & Render | 5 |
| Phase 2 — AI Extraction | 4 |
| Phase 3 — Jobs & API | 4 |
| Phase 4 — Dashboard | 4 |
| Phase 5 — Hardening & Extras | 3 |
| **Total** | **23** |

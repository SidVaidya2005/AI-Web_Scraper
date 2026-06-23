# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 5 — Hardening & Extras (in progress)
**Last completed:** 21 Error handling, timeouts, retries & respectful client (2026-06-23)
**Next:** 22 Second provider (OpenAI) (Phase 5)

**Carry-over into next session:**
- **F21 built:** the respectful client + two deferred loose ends. New module
  `app/fetching/respect.py` (`RespectfulClient`: per-host **rolling-window rate limiter** +
  **TTL robots.txt cache**; `guard` / `check_rate_limit` / `check_robots`), held on
  `app.state.respectful_client` and called by the **runner** (`await guard(url)` before
  `fetch_service.fetch`) — `fetch_service` untouched. Two new errors
  (`RobotsDisallowedError`, `RateLimitedError`, both `FetchError` subclasses, non-transient).
  Render `goto` `PlaywrightTimeoutError` now mapped to a readable `FetchError` in
  `browser.render`. `app.fetching` logger added (`respect.py`, `browser.py`). **No new env
  vars.** Approved plan: `~/.claude/plans/21-error-handling-timeouts-wobbly-pie.md`.
- **Timeouts/retries were already shipped** (F05 fetch timeout, F06 render timeout, F10 LLM
  timeout, F07 bounded transient retry, F14 readable errors) — F21 **verified** them, did not
  re-implement. The genuinely-new work was the respectful client + render-timeout map + logging.
- **F21 locked behaviors:** rate-limit over cap → **reject** (`RateLimitedError`, never holds a
  scheduler slot); rolling window via per-host `deque[float]`, pruned synchronously (atomic, no
  `await` between check+append — same as `scheduler.try_reserve`); **robots fail-open** on
  404/5xx/timeout/unreachable, but **`SSRFError` propagates** (caught before the broad
  `except FetchError`); robots fetched via `http_fetcher` **directly** (SSRF-guarded, size-capped,
  no gate recursion) and parsed with stdlib `RobotFileParser.parse`. Robots TTL is a module
  constant (`_ROBOTS_CACHE_TTL_SECONDS = 3600`), not an env var.
- **`RobotFileParser` gotcha:** a fresh, never-parsed parser has `last_checked == 0` and
  `can_fetch()` returns **False** — so the fail-open "allow" case is represented as **`None`** in
  the cache (return early), never a blank parser. Real parser built only from a 200 body.
- **Placement deviation (documented):** the gate is invoked by the **runner**, not inside
  `fetch_service` (keeps its signature + 23 tests untouched; the runner is the sole caller). The
  `RespectfulClient` module still lives in `app/fetching/`. Annotated under F21 in `build-plan.md`.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F21. Adds `app/fetching/respect.py`,
  `tests/test_respect.py`; modifies `app/fetching/errors.py`, `app/fetching/browser.py`,
  `app/main.py`, `app/jobs/runner.py`, `tests/test_browser.py`, `tests/test_jobs_runner.py`,
  `tests/test_main.py`, and these context docs. HEAD is `4d5f64f 4.20-Result-export`. (Reminder:
  per CLAUDE.md, commits never add a co-author.)

---

## Progress

### Phase 0 — Foundation
- [x] 01 Project scaffold & tooling
- [x] 02 Config & settings
- [x] 03 App skeleton + health endpoint

### Phase 1 — Fetch & Render
- [x] 04 URL safety & SSRF guard
- [x] 05 HTTP fetch (fast path)
- [x] 06 Browser render (fallback)
- [x] 07 Fetch strategy / render decision
- [x] 08 HTML cleaning & content reduction

### Phase 2 — AI Extraction
- [x] 09 LLM provider interface
- [x] 10 Anthropic provider
- [x] 11 Extraction schemas
- [x] 12 Extraction engine

### Phase 3 — Jobs & API
- [x] 13 In-memory job store
- [x] 14 Async job runner
- [x] 15 Job scheduler — concurrency, admission & shutdown
- [x] 16 Extract & jobs API endpoints

### Phase 4 — Dashboard
- [x] 17 Dashboard layout & submission form
- [x] 18 Jobs list & live status
- [x] 19 Job detail & result viewer
- [x] 20 Result export

### Phase 5 — Hardening & Extras
- [x] 21 Error handling, timeouts, retries & respectful client
- [ ] 22 Second provider (OpenAI)
- [ ] 23 Logging, metrics & content-overflow handling

---

## Key Decisions

_(Spec decisions from the 2026-06-21 context review + per-feature decisions. Older/lower-stakes ones are pruned into `build-journal.md` once this passes ~10 bullets.)_

- **Feature 21 Error handling, timeouts, retries & respectful client built (2026-06-23):** new
  `app/fetching/respect.py` `RespectfulClient` — per-host **rolling-window rate limiter** (over cap →
  non-retryable `RateLimitedError`) + **TTL robots.txt cache** (fail-open on 404/5xx/unreachable;
  `SSRFError` propagates; fetched via `http_fetcher` directly, parsed with stdlib `RobotFileParser`).
  Gate invoked by the **runner** before `fetch_service.fetch` (placement deviation — module lives in
  `app/fetching/`). Deferred Playwright render-timeout now mapped to a readable `FetchError`;
  `app.fetching` logger added. Timeouts/retries (F05/F06/F07/F10) verified, not re-built. **No new env
  vars. 268 passing, 1 skipped. Phase 5 opened.** (F16 API decision pruned → `build-journal.md`.)
- **Feature 20 Result export built (2026-06-23):** `GET /jobs/{id}/export?format=json|csv` +
  pure `app/dashboard/export.py`. CSV: single-key list-of-dicts envelope → row-per-dict (union
  columns, first-seen); empty/empty-list → header-only; other shapes → one row; nested → JSON cell;
  `= + - @`-leading cells prefixed `'` (formula-injection). Plain `Response` + attachment header (not
  `StreamingResponse` — in-memory). Unknown id → 404, no-result → 409, bad format → 422. Export
  buttons on the **done** detail page only. **251 passing, 1 skipped. Phase 4 closed.** (F15 scheduler
  decision pruned → `build-journal.md`.)
- **Feature 19 Job detail & result viewer built (2026-06-23):** `templates/job_detail.html`
  (`extends base.html`) + `GET /jobs/{job_id}/view` reading `JobStore.get()`. Unknown id → **styled
  HTML 404** (template not-found state, not JSON); **static snapshot** (no polling — a running job shows
  an in-progress note). Result pretty-printed in the handler (`json.dumps(indent=2)`) and rendered in an
  **autoescaped** `<pre>` — first untrusted-content render, no `| safe`; an injected `<script>` comes
  back `&lt;script&gt;`. F18's plain-text job id is now an `<a href="/jobs/{id}/view">`. **232 passing,
  1 skipped.** (F14 runner decision pruned → `build-journal.md`.)
- **Feature 18 Jobs list & live status built (2026-06-23):** `templates/_jobs_table.html` (id, status,
  mode, created/started/finished UTC `HH:MM:SS`) + `GET /partials/jobs` rendering it from
  `JobStore.list()`; returns **HTTP `286`** when `all(job.is_terminal ...)` (empty → `286` too) else
  `200`. `286` both swaps the body and stops the poll (verified via Context7: htmx default
  `{"code":"[23]..","swap":true}`). Job id is plain text — the `/jobs/{id}/view` link is F19. The F17
  `#jobs` container + submit re-arm untouched. **225 passing, 1 skipped.** (F13 decision pruned →
  `build-journal.md`.)
- **Feature 17 Dashboard layout & submit form built (2026-06-23):** server-rendered shell + working
  form. `app/dashboard/routes.py` `GET /` + form-encoded `POST /submit` (`Form(...)`, reuses
  `require_trusted_origin`) → shared **`app/jobs/submission.py::enqueue`** (atomic reserve→create→submit,
  raising `AtCapacityError`/`SchedulerShuttingDown`); **F16 `/extract` refactored onto `enqueue`**.
  Success re-arms the `#jobs` poller via an `hx-swap-oob` fragment; bad input / capacity / shutdown →
  **inline `200` error** (HTMX won't swap non-2xx), no job. **htmx 2.0.4 vendored same-origin** (no
  CDN/SRI); added dependency **`python-multipart`**. **220 passing, 1 skipped.** (F12 decision pruned →
  `build-journal.md`.)
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

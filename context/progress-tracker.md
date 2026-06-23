# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 4 — Dashboard **in progress**
**Last completed:** 17 Dashboard layout & submission form (2026-06-23)
**Next:** 18 Jobs list & live status (Phase 4 — Dashboard)

**Carry-over into next session:**
- **F17 built:** the dashboard shell + working submit form. `app/dashboard/routes.py` — `GET /`
  renders `index.html`; **form-encoded** `POST /submit` (`Form(...)` fields: `url`, `prompt`,
  `output_schema` as a JSON **string**, `provider`, `render`) reuses `require_trusted_origin` (F16),
  parses the schema (`json.loads`, blank → `None`), builds `ExtractRequest`, and admits via the shared
  `enqueue` helper. On success returns `_submit_result.html` (a "Job queued" note **+ an `hx-swap-oob`
  re-render of `#jobs`** that re-arms the `every 2s` poller); bad input / at-capacity / shutting-down
  return an **inline error fragment with HTTP `200`** (HTMX doesn't swap non-2xx) and create **no job**.
  Templates: `base.html`, `index.html`, `_jobs_container.html` (the poll container, `oob` flag),
  `_submit_result.html`. `static/styles.css` + **vendored `static/htmx.min.js`** (htmx 2.0.4, same-origin —
  no CDN/SRI). `create_app()` now mounts `/static`, sets `app.state.templates`, includes the dashboard
  router. Approved plan: `~/.claude/plans/feature-17-dashboard-quirky-stearns.md`.
- **Shared admission helper (new):** `app/jobs/submission.py` `enqueue(request, *, scheduler, store)
  -> Job` now owns the atomic `try_reserve()` → `create()` → `submit()` sequence; raises
  `AtCapacityError` (gate closed, no job) or re-raises `SchedulerShuttingDown` (after `release()` +
  `mark_error`). **F16's `/extract` handler was refactored onto it** (maps `AtCapacityError` → `429`+
  `Retry-After`, `SchedulerShuttingDown` → `503`) — behaviour unchanged, F16 tests still green.
- **New dependency:** `python-multipart` (added to approved list + `pyproject`/lock) — FastAPI needs it
  to parse `Form(...)`/urlencoded bodies. Used only by `app/dashboard/`.
- **Next is F18 (Jobs list & live status):** build `templates/_jobs_table.html` (id, status, mode,
  timestamps) and `GET /partials/jobs` rendering it from `JobStore.list()`; **return HTTP `286`** once
  every job is terminal (and when empty) so HTMX stops polling. The `#jobs` polling container + its
  re-arm-on-submit are **already in place** (F17); F18 only fills the container and adds the `286` stop.
  Until F18, `GET /partials/jobs` 404s in the browser — expected.
- **Locked store invariants:** only **terminal** jobs are evicted (TTL from `finished_at`; `MAX_JOBS`
  drops oldest terminal); `queued`/`running` are **never** evicted; transitions enforced
  (`mark_running` only from `queued`; `mark_done`/`mark_error` only from non-terminal; `mark_error`
  allowed from `queued`/`running`); `get`/`list`/`mark_*` return **live** Job refs — mutate only via
  `mark_*` under the lock.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F17 — new `app/jobs/submission.py`, `app/dashboard/routes.py`,
  `templates/*.html` (4), `static/styles.css`, `static/htmx.min.js`, `tests/test_dashboard.py`,
  `tests/test_jobs_submission.py`; modified `app/api/extract.py`, `app/main.py`, `pyproject.toml`,
  `uv.lock`, and these context docs (+ `code-standards.md` deps list). HEAD is
  `4efd371 3.16-Extract-jobs-API-endpoints` (F16 **is** committed; the prior tracker note claiming F16
  uncommitted was stale). (Reminder: per CLAUDE.md, commits never add a co-author.)

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
- [ ] 18 Jobs list & live status
- [ ] 19 Job detail & result viewer
- [ ] 20 Result export

### Phase 5 — Hardening & Extras
- [ ] 21 Error handling, timeouts, retries & respectful client
- [ ] 22 Second provider (OpenAI)
- [ ] 23 Logging, metrics & content-overflow handling

---

## Key Decisions

_(Spec decisions from the 2026-06-21 context review + per-feature decisions. Older/lower-stakes ones are pruned into `build-journal.md` once this passes ~10 bullets.)_

- **Feature 17 Dashboard layout & submit form built (2026-06-23):** server-rendered shell + working
  form. `app/dashboard/routes.py` `GET /` + form-encoded `POST /submit` (`Form(...)`, reuses
  `require_trusted_origin`) → shared **`app/jobs/submission.py::enqueue`** (atomic reserve→create→submit,
  raising `AtCapacityError`/`SchedulerShuttingDown`); **F16 `/extract` refactored onto `enqueue`**.
  Success re-arms the `#jobs` poller via an `hx-swap-oob` fragment; bad input / capacity / shutdown →
  **inline `200` error** (HTMX won't swap non-2xx), no job. **htmx 2.0.4 vendored same-origin** (no
  CDN/SRI); added dependency **`python-multipart`**. **220 passing, 1 skipped.** (F12 decision pruned →
  `build-journal.md`.)
- **Feature 16 Extract & jobs API built (2026-06-23):** `app/api/extract.py` — `POST /extract`
  (`202` + `JobResponse`), `GET /jobs` (newest-first), `GET /jobs/{job_id}` (`404`). Atomic
  reserve→create→submit in the handler; **at capacity → `429` + `Retry-After`** (no job created),
  shutdown race → `503` (job terminalized, slot released). New `app/api/security.py`
  `require_trusted_origin` — **lenient** CSRF Origin check (missing Origin allowed; present host ∉
  `ALLOWED_HOSTS` → `403`), a **shared** route dependency F17's dashboard POST reuses. Router wired into
  `create_app()`. **206 passing, 1 skipped. Phase 3 closed.** (F11 extraction-schemas decision pruned →
  `build-journal.md`.)
- **Feature 15 Job scheduler built (2026-06-23):** `app/jobs/scheduler.py` `Scheduler` +
  `SchedulerShuttingDown`. **Two bounds:** `MAX_CONCURRENT_JOBS` semaphore (running) **and** a
  synchronous atomic `try_reserve()` (`int` check-and-increment, no `await`) capping in-flight+waiting
  at `MAX_QUEUED_JOBS`. `submit()` is sync, retains the task ref (no fire-and-forget); the admission slot
  is released in the task's `finally` (one release per task, even on cancel). `shutdown()` closes
  admission → drains within `SHUTDOWN_GRACE_SECONDS` → cancels stragglers → sweeps `store.list()` marking
  non-terminal jobs `error`; lifespan drains **before** `browser_manager.aclose()`. Reuses F14's
  `RunnerState`. **196 passing, 1 skipped.** (Pre-code F15 spec bullet pruned → `build-journal.md`.)
- **Feature 14 Async job runner built (2026-06-23):** `app/jobs/runner.py`
  `run_job(job_id, *, app_state)` — the pipeline driver and **top-level error boundary** (never
  raises): `mark_running → fetch_service.fetch(str(url)) → cleaner.clean → registry.get_provider →
  engine.extract → mark_done`. Known errors (`ProviderError`/`FetchError`+subclasses/`ValidationError`)
  → `mark_error(str(exc))`; unknown → generic non-leaky message (traceback logged). `app_state` typed by
  a local **`RunnerState` Protocol** (`job_store`/`browser_manager`/`settings`); a best-effort
  **`_terminalize`** swallows `JobStateError` so an already-terminal/missing job can't break "never
  raises". Provider is **built in the runner** (`registry.get_provider(settings, override=request.provider)`)
  and injected (F12 contract). Lifespan now wires `app.state.job_store`. **185 passing, 1 skipped.**
  (F10 Anthropic-provider decision pruned → `build-journal.md`.)
- **Feature 13 In-memory job store built (2026-06-23):** `app/jobs/models.py` (`Job` +
  `is_terminal`; `JobStatus(StrEnum)`) and `app/jobs/store.py` `JobStore` — `asyncio.Lock`-guarded
  `dict`, **lazy** `_evict` (TTL from `finished_at` + oldest-**terminal** `MAX_JOBS` sweep;
  `queued`/`running` never evicted), newest-first via `reversed(insertion)`, and **enforced
  transitions** (`mark_running` from `queued`; `mark_done`/`mark_error` non-terminal only; missing
  id / terminal mutation → `JobStateError`). `JobResponse` landed in `app/models.py` (echoes
  `url`+`prompt`; `status: str`; `Job` under `TYPE_CHECKING` to sever the `models ↔ jobs.models`
  cycle). Lifespan wiring deferred to F14. **174 passing, 1 skipped.** (F07 fetch-strategy decision
  pruned → `build-journal.md`.)
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

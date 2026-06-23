# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 3 — Jobs & API **complete** → Phase 4 — Dashboard next
**Last completed:** 16 Extract & jobs API endpoints (2026-06-23)
**Next:** 17 Dashboard layout & submission form (Phase 4 — Dashboard)

**Carry-over into next session:**
- **F16 built:** `app/api/extract.py` — `POST /extract` (`202` + `JobResponse`), `GET /jobs`
  (newest-first `list[JobResponse]`), `GET /jobs/{job_id}` (`404` if unknown/evicted). Handler runs the
  canonical orchestration: `try_reserve()` → `try: await store.create(req) except BaseException:
  release(); raise` → `try: scheduler.submit(job.id) except SchedulerShuttingDown: release(); await
  store.mark_error(..., "server shutting down"); raise 503 from None`. **At capacity** (`try_reserve()`
  False) → **`429` + `Retry-After: 5`**, no job created; the rare shutdown race → **`503`**. Plus
  `app/api/security.py` `require_trusted_origin` — **lenient** CSRF Origin check (missing Origin allowed;
  present Origin whose host ∉ `ALLOWED_HOSTS` → `403`), wired as a route dependency on `POST /extract`.
  Router included in `create_app()`. Suite **206 passing, 1 skipped** (196 prior + 10 new), ruff clean.
  Approved plan: `~/.claude/plans/f16-extract-abundant-stearns.md`.
- **Next is F17 (Dashboard layout & submission form):** `templates/base.html` (loads HTMX +
  `static/styles.css`), `templates/index.html` (URL/prompt/schema form **+ a default-unchecked `render`
  checkbox** with a short local-network-risk note). `app/dashboard/routes.py` `GET /` rendering
  `index.html`; a **form-handling** POST route taking `Form(...)` fields (incl. `render: bool = False`)
  that **reuses `require_trusted_origin`** (F16) and calls the **same** job service the API uses
  (form-encoded, not JSON — don't point the form at the JSON `/extract`). Its response **re-renders the
  polling container with the `every 2s` trigger** so polling restarts even if it had stopped. `Jinja2Templates`
  is mounted on `app.state.templates` in `create_app()` (not wired yet — F17 adds it) and `StaticFiles`
  at `/static`.
- **F16 → F17 reuse:** the Origin check is the shared dependency `app.api.security.require_trusted_origin`
  — import and `Depends(...)` it on the dashboard POST; do **not** re-implement. The job service the
  dashboard calls is the same `scheduler.try_reserve()/submit()` + `store.create()` sequence; consider a
  thin shared helper if F17 finds the orchestration duplicated (currently it lives inline in the handler).
- **Locked store invariants:** only **terminal** jobs are evicted (TTL from `finished_at`; `MAX_JOBS`
  drops oldest terminal); `queued`/`running` are **never** evicted; transitions enforced
  (`mark_running` only from `queued`; `mark_done`/`mark_error` only from non-terminal; `mark_error`
  allowed from `queued`/`running`); `get`/`list`/`mark_*` return **live** Job refs — mutate only via
  `mark_*` under the lock.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F16 — `app/api/extract.py` (new), `app/api/security.py`
  (new), `tests/test_api_extract.py` (new); `app/main.py` (modified) and these context docs. HEAD is
  `49d5c88 3.15-Job-scheduler-concurrency-admission-shutdown` (F15 **is** committed — the prior pending
  commit-or-proceed decision was resolved). (Reminder: per CLAUDE.md, commits never add a co-author.)

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
- [ ] 17 Dashboard layout & submission form
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
- **Feature 12 Extraction engine built (2026-06-23):** `app/extraction/engine.py`
  `extract(content, *, prompt, schema, provider: LLMProvider)` — `normalize_for_strict(schema)`
  → `provider.extract(...)` → `validate_output` against the **original** schema, wrapping the
  jsonschema `ValidationError` into `ProviderError("extraction did not match schema: …")`. The
  **provider is injected by the F14 runner** (engine reads no settings, never calls the registry)
  — a **documented deviation** from `architecture.md`'s data-flow (annotated in `build-plan.md`
  F12) chosen for a registry-free, trivially-testable engine. `schema=None` skips validation; a
  provider `ProviderError` propagates unchanged (runner is the boundary). **155 passing, 1
  skipped. Phase 2 closed.** (F09 provider-interface decision pruned → `build-journal.md`.)
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

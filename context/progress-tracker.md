# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 3 — Jobs & API (in progress)
**Last completed:** 15 Job scheduler — concurrency, admission & shutdown (2026-06-23)
**Next:** 16 Extract & jobs API endpoints (Phase 3 — Jobs & API)

**Carry-over into next session:**
- **F15 built:** `app/jobs/scheduler.py` — `Scheduler` (`try_reserve`/`release`/`submit`/`shutdown`) +
  `SchedulerShuttingDown`. **Two bounds:** a `MAX_CONCURRENT_JOBS` semaphore (running subset) **and** a
  synchronous atomic `try_reserve()` (plain-`int` `_reserved`, check-and-increment with **no `await`
  between**) capping in-flight+waiting at `MAX_QUEUED_JOBS` (returns False at cap or while draining).
  `submit()` is **sync**, `create_task`s `_run` and **retains the ref** (no fire-and-forget); `_run` =
  `try: async with sem: await runner.run_job(...) finally: self.release()` → exactly one release per
  task, even on cancel. `shutdown()`: `_draining=True` → `asyncio.wait(grace)` → cancel stragglers →
  `gather` → sweep `store.list()` marking non-terminal jobs `error` ("server shutting down"). Lifespan
  wires `app.state.scheduler` and **drains BEFORE `browser_manager.aclose()`**. Suite **196 passing,
  1 skipped** (185 prior + 11 new). Approved plan: `~/.claude/plans/f15-job-scheduler-woolly-dragonfly.md`.
- **Next is F16 (Extract & jobs API endpoints):** `app/api/extract.py` — `POST /extract` (`202` +
  `job_id`; `503`/`429` when `scheduler.try_reserve()` returns False — atomic, **before** `create()`),
  `GET /jobs/{id}`, `GET /jobs`. The handler owns the orchestration F15 left to it:
  `try_reserve()` → `try: job = await store.create(req) except BaseException: release(); raise` →
  `try: scheduler.submit(job.id) except SchedulerShuttingDown: release(); await store.mark_error(job.id,
  "server shutting down"); raise 503`. Reject root-non-object / out-of-subset `output_schema` with `422`
  (already wired via the `ExtractRequest` `@field_validator` → `InvalidSchemaError(ValueError)` from F11).
  Add the **Origin check on `POST /extract`** (state-changing; v1 CSRF baseline alongside the Host
  allow-list). Return the declared `JobResponse` (`from_job`). Verify with TestClient (stub the runner).
- **F15 → F16 contract:** the scheduler exposes `try_reserve()` (sync bool), `release()` (sync),
  `submit(job_id)` (sync; raises `SchedulerShuttingDown` only while draining), `shutdown()` (async).
  `run_job` already owns all error handling and never raises; the scheduler manages
  concurrency/admission/lifecycle only. The handler is the **only** place reserve→create→submit is
  orchestrated.
- **Locked store invariants:** only **terminal** jobs are evicted (TTL from `finished_at`; `MAX_JOBS`
  drops oldest terminal); `queued`/`running` are **never** evicted; transitions enforced
  (`mark_running` only from `queued`; `mark_done`/`mark_error` only from non-terminal; `mark_error`
  allowed from `queued`/`running`); `get`/`list`/`mark_*` return **live** Job refs — mutate only via
  `mark_*` under the lock.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F15 — `app/jobs/scheduler.py` (new),
  `tests/test_jobs_scheduler.py` (new); `app/main.py`, `tests/test_main.py` (modified) and these context
  docs. HEAD is `60aaa19 3.14-Async-job-runner`. F12/F13/F14 are **committed** (the earlier "uncommitted
  F12–F14" note was stale — verified via `git log`). (Reminder: per CLAUDE.md, commits never add a
  co-author.)
- **OPEN — pending decision:** session ended right after F15 verified (196 passing / 1 skipped, ruff
  clean). Developer was asked "commit F15 now, or move on to F16?" and has **not** answered yet — decide
  this first next session before starting F16.

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
- [ ] 16 Extract & jobs API endpoints

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
- **Feature 11 Extraction schemas built (2026-06-23):** `app/extraction/schemas.py` —
  `validate_request_schema` (root `type:object` + a **targeted denylist** of out-of-subset
  keywords → `InvalidSchemaError(ValueError)`), `normalize_for_strict` (deep copy; sets
  `additionalProperties:false` + `required:[all keys]` on every object node with `properties` —
  for the provider's strict tool only), and `validate_output` (`Draft202012Validator` +
  `FORMAT_CHECKER` against the **original** user schema; lets jsonschema `ValidationError`
  propagate for F12 to wrap). The subset walk is structure-aware (`_iter_subschemas`), so a
  property literally named `not` is accepted. `app/models.py` `ExtractRequest` wires the gate via a
  `@field_validator` (→ 422 in F16); **`JobResponse` deferred to F13/F16**. **149 passing, 1
  skipped.** (F08 cleaner decision pruned → `build-journal.md`.)
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

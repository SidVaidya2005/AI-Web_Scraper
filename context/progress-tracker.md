# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 3 — Jobs & API (in progress)
**Last completed:** 14 Async job runner (2026-06-23)
**Next:** 15 Job scheduler — concurrency, admission & shutdown (Phase 3 — Jobs & API)

**Carry-over into next session:**
- **F14 built:** `app/jobs/runner.py` — `run_job(job_id, *, app_state)` drives
  `mark_running → fetch_service.fetch(str(url), …, render=…) → cleaner.clean → registry.get_provider →
  engine.extract → mark_done(result, mode)`; the project's **error boundary** (never raises). Known
  errors (`ProviderError`/`FetchError`+subclasses/`ValidationError`) → `mark_error(str(exc))`; unknown
  → generic `"internal error — see server logs"` (traceback logged). A local **`RunnerState` Protocol**
  (`job_store`/`browser_manager`/`settings`) types `app_state`; a best-effort **`_terminalize`** swallows
  `JobStateError` so an already-terminal/missing job can't make the boundary raise. **Lifespan now wires
  `app.state.job_store = JobStore(settings=settings)`** (F13-deferred). Suite **185 passing, 1 skipped**
  (174 prior + 11 new). Approved plan: `~/.claude/plans/f14-async-job-vivid-harbor.md`.
- **Next is F15 (Job scheduler — concurrency, admission & shutdown):** `app/jobs/scheduler.py` —
  `try_reserve()`/`release()`/`submit(job_id)` + `SchedulerShuttingDown`. Run `run_job` under a
  `MAX_CONCURRENT_JOBS` semaphore with **retained task refs** (no fire-and-forget `create_task`); atomic
  `try_reserve()` (sync check-and-increment, no `await`) caps in-flight+waiting at `MAX_QUEUED_JOBS` →
  over cap `503`/`429`, no job created; `release()` on terminal / failed-create / failed-submit. Admission
  **closes first on shutdown** (`try_reserve()` → False); a `submit()` failing after reserve+create
  `release()`s **and** `mark_error`s the job. **Lifespan shutdown must drain the scheduler BEFORE
  `browser_manager.aclose()`** (in-flight renders finish first) — the `app/main.py` finally block is
  ready for this insertion.
- **F14 → F15 contract:** the scheduler calls `run_job(job_id, app_state=app_state)`; `run_job` already
  owns all error handling and never raises, so the scheduler only manages concurrency/admission/lifecycle.
  The **`RunnerState` Protocol is reusable** as the scheduler's `app_state` type.
- **Locked store invariants:** only **terminal** jobs are evicted (TTL from `finished_at`; `MAX_JOBS`
  drops oldest terminal); `queued`/`running` are **never** evicted; transitions enforced
  (`mark_running` only from `queued`; `mark_done`/`mark_error` only from non-terminal; `mark_error`
  allowed from `queued`/`running`); `get`/`list`/`mark_*` return **live** Job refs — mutate only via
  `mark_*` under the lock.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F14 — `app/jobs/runner.py` (new), `tests/test_jobs_runner.py`
  (new); `app/main.py`, `tests/test_main.py` (modified) — **plus still-uncommitted F12** (`app/extraction/
  engine.py`, `tests/test_extraction_engine.py`) **and F13** (`app/jobs/models.py`, `app/jobs/store.py`,
  `tests/test_jobs_models.py`, `tests/test_jobs_store.py` new; `app/models.py`, `tests/test_models.py`
  modified) and these context docs. HEAD is `a4f3208 2.11-Extraction-schemas`.
  (Reminder: per CLAUDE.md, commits never add a co-author.)
- **OPEN — pending decision:** F12, F13 **and** F14 are all complete and verified (185 passing / 1
  skipped, ruff clean) but uncommitted; HEAD is still `a4f3208 2.11-Extraction-schemas`. Decide the
  commit strategy (e.g. F12 → F13 → F14 as three commits) before/at the next session.

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
- [ ] 15 Job scheduler — concurrency, backpressure & shutdown
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
- **Scheduler bounded by concurrency AND atomic admission** (15): `MAX_CONCURRENT_JOBS` semaphore + retained task refs + `try_reserve()` (synchronous check-and-increment, no `await` → no TOCTOU) capping in-flight+waiting at `MAX_QUEUED_JOBS`; over cap → `503`/`429`, no job created; `release()` on terminal / failed-create / failed-submit. Admission **closes first on shutdown** (`try_reserve()` → False), and a `submit()` that fails after reserve+create releases the slot **and** terminalizes the job (no `queued` zombie). Shutdown drains **before** the browser closes.
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

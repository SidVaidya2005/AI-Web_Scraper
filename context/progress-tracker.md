# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 4 — Dashboard **in progress**
**Last completed:** 19 Job detail & result viewer (2026-06-23)
**Next:** 20 Result export (Phase 4 — Dashboard)

**Carry-over into next session:**
- **F19 built:** the single-job detail page. New `templates/job_detail.html` (`extends base.html`):
  request summary (url, prompt, provider, render), status/mode/timestamps, then the result `<pre>`
  (done) / error message (error) / "still in progress" note (queued/running). New
  `GET /jobs/{job_id}/view` in `app/dashboard/routes.py` reads `JobStore.get()`; an unknown/evicted id
  renders the template's **not-found state with HTTP 404** (styled HTML, not JSON). Result is
  pretty-printed in the handler (`json.dumps(indent=2, ensure_ascii=False)`) and rendered in an
  **autoescaped** `<pre>` — no `| safe`. F18's plain-text id is now an `<a href="/jobs/{id}/view">` in
  `_jobs_table.html`. Detail-page CSS appended to `static/styles.css` (`.detail-meta`,
  `pre.result-json`, `.back`). Approved plan: `~/.claude/plans/f19-job-detail-calm-hellman.md`.
- **F19 escaping note (important):** Jinja autoescapes **double quotes too** (`"` → `&#34;`), so the
  rendered `result_json` shows escaped quotes in the raw HTML (renders fine in a browser). Tests assert
  on word fragments + the escaped `&lt;script&gt;...` form, not literal JSON punctuation. The XSS test
  injects `<script>alert(1)</script>` into `result` and asserts the raw tag is absent and the escaped
  form present.
- **Test trick (reused, extended for F19):** monkeypatch `app.state.job_store.get` (and `.list`) to
  return crafted `Job`s for deterministic endpoint tests — safe at shutdown because
  `Scheduler._terminalize_survivors` swallows the `JobStateError` for ids absent from the real store.
  A `_detail_job(...)` helper builds a Job carrying a result/error.
- **Next is F20 (Result export):** `GET /jobs/{id}/export?format=json|csv` streaming a file response
  generated on the fly (no persistence); add export buttons to `job_detail.html`. CSV rules (explicit):
  flatten a list-of-objects **envelope** to rows with a stable column order (union of keys); single
  object → one row; empty result → header only; nested values → JSON-encoded cells; **escape
  formula-injection** (cells leading with `= + - @` are prefixed). Verify: JSON export equals the stored
  result; CSV flattens tabular/nested/empty/heterogeneous correctly and neutralizes a `=`-leading cell.
- **Locked store invariants:** only **terminal** jobs are evicted (TTL from `finished_at`; `MAX_JOBS`
  drops oldest terminal); `queued`/`running` are **never** evicted; transitions enforced
  (`mark_running` only from `queued`; `mark_done`/`mark_error` only from non-terminal; `mark_error`
  allowed from `queued`/`running`); `get`/`list`/`mark_*` return **live** Job refs — mutate only via
  `mark_*` under the lock.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F19 — new `templates/job_detail.html`; modified
  `app/dashboard/routes.py`, `templates/_jobs_table.html`, `static/styles.css`,
  `tests/test_dashboard.py`, and these context docs. HEAD is `a891721 4.18-Jobs-list-&-live-status`
  (F18 is committed). (Reminder: per CLAUDE.md, commits never add a co-author.)

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
- [ ] 20 Result export

### Phase 5 — Hardening & Extras
- [ ] 21 Error handling, timeouts, retries & respectful client
- [ ] 22 Second provider (OpenAI)
- [ ] 23 Logging, metrics & content-overflow handling

---

## Key Decisions

_(Spec decisions from the 2026-06-21 context review + per-feature decisions. Older/lower-stakes ones are pruned into `build-journal.md` once this passes ~10 bullets.)_

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
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

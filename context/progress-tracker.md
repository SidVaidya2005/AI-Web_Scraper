# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 4 — Dashboard **complete** → Phase 5 — Hardening & Extras next
**Last completed:** 20 Result export (2026-06-23)
**Next:** 21 Error handling, timeouts, retries & respectful client (Phase 5)

**Carry-over into next session:**
- **F20 built:** result export. New **pure** module `app/dashboard/export.py` (`result_to_json`,
  `result_to_csv`, `_escape_formula`, `_rows_for`, `_columns_for`, `_render_cell`) — stdlib only
  (`csv`/`io`/`json`), no FastAPI/job-state. New `GET /jobs/{job_id}/export` in
  `app/dashboard/routes.py`: read-only (no Origin check), `format: Literal["json","csv"] = "json"`,
  returns a plain `Response` with `Content-Disposition: attachment; filename="job-{id}.{ext}"`.
  Two `<a class="export-btn">` links added to the **done** block of `job_detail.html`; `.exports`/
  `.export-btn` CSS appended. Approved plan: `~/.claude/plans/f20-result-export-elegant-muffin.md`.
- **F20 CSV shape rules (locked):** a **single key whose value is a list of dicts** → one row per dict,
  columns = union of keys in first-seen order; an **empty list envelope** (`{"items": []}`) or empty
  result → header-only (no data rows); **any other shape** (incl. a single key holding a list of
  *scalars*) → one row. Nested dict/list cells are JSON-encoded; `None` → blank; cells leading with
  `= + - @` get a `'` prefix (negatives like `-5` are escaped too — accepted, per spec). `csv.writer`
  handles comma/quote/newline quoting; formula-escaping is applied to **header and data** cells.
- **F20 status codes:** unknown/evicted id → **404**; job exists but `result is None`
  (queued/running/error) → **409**; bad `?format` → **422** (Literal validation, before the handler).
  Export is a plain `Response`, **not** `StreamingResponse` — the result is already in-memory
  (documented deviation from the build-plan's literal "streaming" wording).
- **Test trick (reused for F20):** monkeypatch `app.state.job_store.get`/`.list` to return crafted
  `Job`s for deterministic endpoint tests — safe at shutdown because
  `Scheduler._terminalize_survivors` swallows the `JobStateError` for ids absent from the real store.
  CSV tests parse output back with `csv.reader` so they assert on **values, not quoting**.
- **Locked store invariants:** only **terminal** jobs are evicted (TTL from `finished_at`; `MAX_JOBS`
  drops oldest terminal); `queued`/`running` are **never** evicted; transitions enforced
  (`mark_running` only from `queued`; `mark_done`/`mark_error` only from non-terminal; `mark_error`
  allowed from `queued`/`running`); `get`/`list`/`mark_*` return **live** Job refs — mutate only via
  `mark_*` under the lock.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F19 + F20. F20 adds `app/dashboard/export.py`,
  `tests/test_export.py`; modifies `app/dashboard/routes.py`, `templates/job_detail.html`,
  `static/styles.css`, `tests/test_dashboard.py`, and these context docs. (F19 from the prior session
  is also still uncommitted: `templates/job_detail.html`, `app/dashboard/routes.py`,
  `templates/_jobs_table.html`, `static/styles.css`, `tests/test_dashboard.py`.) HEAD is
  `a891721 4.18-Jobs-list-&-live-status`. (Reminder: per CLAUDE.md, commits never add a co-author.)

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
- [ ] 21 Error handling, timeouts, retries & respectful client
- [ ] 22 Second provider (OpenAI)
- [ ] 23 Logging, metrics & content-overflow handling

---

## Key Decisions

_(Spec decisions from the 2026-06-21 context review + per-feature decisions. Older/lower-stakes ones are pruned into `build-journal.md` once this passes ~10 bullets.)_

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
- **Feature 16 Extract & jobs API built (2026-06-23):** `app/api/extract.py` — `POST /extract`
  (`202` + `JobResponse`), `GET /jobs` (newest-first), `GET /jobs/{job_id}` (`404`). Atomic
  reserve→create→submit in the handler; **at capacity → `429` + `Retry-After`** (no job created),
  shutdown race → `503` (job terminalized, slot released). New `app/api/security.py`
  `require_trusted_origin` — **lenient** CSRF Origin check (missing Origin allowed; present host ∉
  `ALLOWED_HOSTS` → `403`), a **shared** route dependency F17's dashboard POST reuses. Router wired into
  `create_app()`. **206 passing, 1 skipped. Phase 3 closed.** (F11 extraction-schemas decision pruned →
  `build-journal.md`.)
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

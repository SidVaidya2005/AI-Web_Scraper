# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 5 — Hardening & Extras (complete)
**Last completed:** 23 Logging, metrics & content-overflow handling (2026-06-24)
**Next:** — all 23 features built; the build plan is complete.

**Carry-over into next session:**
- **F23 built (closes the build plan):** the pipeline is now observable. `cleaner.clean()` returns a
  frozen `CleanResult(text, truncated)`; `Job` + `JobResponse` carry `fetch_ms`/`extract_ms`/
  `total_ms`/`content_truncated`; the runner times stages with `perf_counter`, logs the lifecycle
  (`running → fetched → done`, INFO) plus a truncation `WARNING`, and `enqueue` logs a request-
  `accepted` line; the detail page shows timings + a truncation note. **No new deps, no new env
  vars.** Approved plan: `~/.claude/plans/f23-logging-metrics-linear-lantern.md`.
- **Scope choices to remember:** content-overflow is **detect & signal only** (no chunk-and-merge —
  still the documented future follow-up); there is **no separate `render_ms`** (`fetch_ms` covers
  render; `mode` says which); timing is recorded **on `done` only** (error path leaves metrics
  `None`); logging stayed **plain text** (no JSON). `clean()`'s return-type change rippled only to the
  runner (its sole caller).
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F23. Adds `CleanResult` to `app/cleaning/cleaner.py`;
  modifies `app/jobs/models.py`, `app/jobs/store.py`, `app/jobs/runner.py`, `app/jobs/submission.py`,
  `app/models.py`, `templates/job_detail.html`, `static/styles.css`, the five test files above, and
  these context docs. HEAD is `6d3b657 5.22-Second-provider(OpenAI)`. (Reminder: per CLAUDE.md,
  commits never add a co-author.)

**Open question — no feature is queued (the 23-item plan is done).** Candidate next directions, all
documented as follow-ups in the context docs (none scoped/approved yet — confirm with the developer
before starting):
- **Commit F23** (the only immediately-pending action).
- **Token-aware budgeting / chunk-and-merge** for pages over `MAX_CONTENT_CHARS` — the deferred deep
  version of overflow handling (F23 only detects/signals truncation).
- **IP-pinning / byte-counting SSRF egress proxy** in front of both fetchers — the complete fix for
  the browser path's residual DNS-rebinding risk; would let `render` be safe-by-default instead of
  opt-in (see `architecture.md` invariants).
- **Auth + CSRF tokens** — hard prerequisites before any public/remote bind (today: loopback-local /
  trusted-private-network only).
- **Smaller hardening:** failed-job timing (record metrics on the `error` path too), provider/client
  caching/lifecycle (noted F21+), structured JSON logging if log aggregation is ever needed.

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
- [x] 22 Second provider (OpenAI)
- [x] 23 Logging, metrics & content-overflow handling

---

## Key Decisions

_(Spec decisions from the 2026-06-21 context review + per-feature decisions. Older/lower-stakes ones are pruned into `build-journal.md` once this passes ~10 bullets.)_

- **Feature 23 Logging, metrics & content-overflow handling built (2026-06-24) — closes the build
  plan:** per-job timing (`fetch_ms`/`extract_ms`/`total_ms`, rounded ms) measured in the runner with
  `perf_counter` and stored on `Job` + `JobResponse` + the detail page; enriched plain-text lifecycle
  INFO logs (`running → fetched → done`) plus a request-`accepted` line in `enqueue`. Content-overflow
  is **detect & signal only**: `cleaner.clean()` returns `CleanResult(text, truncated)`, the runner
  records `content_truncated` + logs a `WARNING`, the detail page shows a note — **no chunk-and-merge**
  (still a future follow-up). No separate `render_ms` (`fetch_ms` covers render; `mode` says which);
  timing recorded on `done` only. **No new deps/env vars. 284 passing, 1 skipped.** (F18 dashboard
  decision pruned → `build-journal.md`.)
- **Feature 22 Second provider (OpenAI) built (2026-06-24):** `app/providers/openai_provider.py`
  (`OpenAIProvider` via **Chat Completions** forced function calling + strict) mirrors the Anthropic
  contract; shared framing hoisted to `app/providers/_prompts.py` (`SYSTEM_PROMPT`/`TOOL_NAME`/
  `build_user_message`, Anthropic refactored onto it). **Only real divergence:** OpenAI `arguments`
  is a JSON **string** → `json.loads` + object-envelope guard. Registry `openai` branch **fails fast**
  on missing key/model (`OPENAI_MODEL` has no default); token param is `max_completion_tokens`. Engine
  unchanged (F11 `normalize_for_strict` already satisfies OpenAI strict). **No new deps/env vars. 278
  passing, 1 skipped.** (F17 dashboard decision pruned → `build-journal.md`.)
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
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

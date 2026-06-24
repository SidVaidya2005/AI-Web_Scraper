# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 5 — Hardening & Extras (in progress)
**Last completed:** 22 Second provider (OpenAI) (2026-06-24)
**Next:** 23 Logging, metrics & content-overflow handling (Phase 5)

**Carry-over into next session:**
- **F22 built:** the OpenAI provider proves the abstraction. New `app/providers/openai_provider.py`
  (`OpenAIProvider`, **Chat Completions** + forced function calling + strict) and new shared
  `app/providers/_prompts.py` (`SYSTEM_PROMPT`, `TOOL_NAME`, `build_user_message`) — Anthropic was
  refactored onto it so the prompt-injection framing is byte-identical across providers. Registry
  gained an `openai` branch that **fails fast** on missing key/model. **No new deps** (`openai`
  2.43.0 already installed), **no new env vars**. Approved plan:
  `~/.claude/plans/f22-second-provider-fizzy-stardust.md`.
- **The one real divergence from Anthropic:** OpenAI tool-call `arguments` is a JSON **string** →
  `json.loads` + guard (unparseable → `ProviderError`; non-`dict` like a top-level list →
  `ProviderError`). Anthropic's `block.input` is already a dict. Token param is
  `max_completion_tokens` (Anthropic uses `max_tokens`), so `_MAX_TOKENS = 4096` stays local to
  each provider, not shared.
- **Engine unchanged:** `normalize_for_strict()` (F11) already emits the closed schema
  (`additionalProperties:false` + all-`required`) that OpenAI strict needs, so the provider just
  sets `strict: true`; no-schema path mirrors Anthropic (loose params, no strict).
- **Registry:** `OPENAI_MODEL` has no default — missing key → `ProviderError("OPENAI_API_KEY not
  configured")`, missing model → `ProviderError("OPENAI_MODEL not configured")` at `get_provider`.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F22. Adds `app/providers/openai_provider.py`,
  `app/providers/_prompts.py`; modifies `app/providers/anthropic_provider.py`,
  `app/providers/registry.py`, `tests/test_providers.py`, and these context docs. HEAD is
  `fdc0277 5.21-Error-handling,timeouts,retries`. (Reminder: per CLAUDE.md, commits never add a
  co-author.)

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
- [ ] 23 Logging, metrics & content-overflow handling

---

## Key Decisions

_(Spec decisions from the 2026-06-21 context review + per-feature decisions. Older/lower-stakes ones are pruned into `build-journal.md` once this passes ~10 bullets.)_

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
- **Feature 18 Jobs list & live status built (2026-06-23):** `templates/_jobs_table.html` (id, status,
  mode, created/started/finished UTC `HH:MM:SS`) + `GET /partials/jobs` rendering it from
  `JobStore.list()`; returns **HTTP `286`** when `all(job.is_terminal ...)` (empty → `286` too) else
  `200`. `286` both swaps the body and stops the poll (verified via Context7: htmx default
  `{"code":"[23]..","swap":true}`). Job id is plain text — the `/jobs/{id}/view` link is F19. The F17
  `#jobs` container + submit re-arm untouched. **225 passing, 1 skipped.** (F13 decision pruned →
  `build-journal.md`.)
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

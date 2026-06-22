# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 2 — AI Extraction (in progress)
**Last completed:** 09 LLM provider interface (2026-06-22)
**Next:** 10 Anthropic provider (Phase 2 — AI Extraction)

**Carry-over into next session:**
- **Phase 2 has started.** The provider *contract* is now in place (F09); next is the
  first concrete provider — `app/providers/anthropic_provider.py` (F10) via `AsyncAnthropic`,
  forced tool-use, plus `app/providers/registry.py`.
- **F09 contract is built:** `app/providers/base.py` exposes exactly two names —
  `ProviderError(RuntimeError)` and a `@runtime_checkable` `LLMProvider` Protocol with one
  async, keyword-only method `extract(*, content, prompt, json_schema) -> dict[str, Any]`.
  Interface-only: **no SDK import, no registry, no concrete provider** (those are F10). Import
  from the real path (`from app.providers.base import LLMProvider, ProviderError`) — no barrel
  re-export in `__init__.py`.
- **`@runtime_checkable` chosen** (developer decision) so the test asserts
  `isinstance(fake, LLMProvider)` plus a non-conforming `object()` failing it; the awaited
  `extract()` returning a `dict` is the real conformance proof (isinstance only checks method
  presence, not signature).
- **F10 will be the first feature to import an SDK** (`anthropic`) — keep it **only** inside
  `app/providers/`. Use the **`claude-api` skill** for current model ids before coding
  (`ANTHROPIC_MODEL` default `claude-sonnet-4-6`; id always from settings, never literal),
  and Context7 `/anthropics/anthropic-sdk-python` for the SDK shape. Anthropic key is read as
  `SecretStr` in `Settings` (F02) — provider reads it via `.get_secret_value()`.
- **Test seams / isolation (unchanged):** test-per-module (`tests/test_providers.py`); tests
  build `Settings(_env_file=None, …)` so the dev shell can't bleed in; provider SDK calls get
  **mocked** in F10 (no live LLM in the suite).
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F09 — `app/providers/base.py`,
  `tests/test_providers.py` (both new, untracked).
- **Prior OPEN item resolved:** F08 *was* committed (`27097ed 1.8-HTML-cleaning…`); the old
  "F08 not yet committed" note was stale. (Reminder: per CLAUDE.md, commits never add a
  co-author.)
- **OPEN — pending decision (resolve first next session):** commit F09 now, or proceed
  straight to F10? Developer was asked at session end and hadn't answered. The approved F09
  plan lives at `~/.claude/plans/09-llm-provider-playful-breeze.md` (already fully realized in
  code — reference only).

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
- [ ] 10 Anthropic provider
- [ ] 11 Extraction schemas
- [ ] 12 Extraction engine

### Phase 3 — Jobs & API
- [ ] 13 In-memory job store
- [ ] 14 Async job runner
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

- **Feature 09 provider interface built (2026-06-22):** `app/providers/base.py` —
  `ProviderError(RuntimeError)` + a `@runtime_checkable` `LLMProvider` Protocol with one
  async, keyword-only `extract(*, content, prompt, json_schema) -> dict[str, Any]` (object
  envelope; raises `ProviderError`). Interface-only — **no SDK / registry / concrete
  provider** (F10); import from the real path, no `__init__` barrel. `tests/test_providers.py`
  asserts `isinstance(fake, LLMProvider)`, a non-conformer fails it, and `extract()` awaits to
  a `dict`. **Phase 2 begun.** (F05 HTTP-fetch decision pruned → `build-journal.md`.)
- **Feature 06 browser render built (2026-06-22):** `app/fetching/browser.py` —
  `BrowserManager` (lazy double-checked Chromium launch; `aclose()` no-op if never launched)
  + `render(url, *, browser, settings) -> FetchResult` (`await`-ed guard route on every
  request, `service_workers="block"`, `route_web_socket` closes all WS, content-length budget
  + post-render backstop, **real** `goto`/`page.url` metadata, `mode="browser"`). **Test
  strategy = hybrid:** fully-mocked unit tests (`tests/test_browser.py`) + one gated
  real-Chromium integration test (`tests/test_browser_integration.py`); CI now installs
  Chromium. **Lifespan wiring deferred to F07** (decision); render-timeout→taxonomy mapping
  deferred to F21. Full detail in `build-journal.md`.
- **Feature 07 fetch strategy built (2026-06-22):** `app/fetching/fetch_service.py`
  (`fetch(url, *, browser_manager, settings, render=False)` + `needs_render`) implements the
  architecture **fallback matrix**. `_fetch_http` retries **only** `TransientFetchError` up to
  `FETCH_MAX_RETRIES` (SSRF/oversize propagate, never retried); render runs only on
  `render=True` via lazy `browser_manager.get()` (so `render=False` **never launches
  Chromium**); the rendered result is re-checked for 2xx+HTML. `needs_render` = selectolax
  visible-text threshold (`_MIN_VISIBLE_TEXT_CHARS`, script/style dropped first — no env var).
  **Lifespan now wires `app.state.browser_manager`** (+ `aclose()` on shutdown). Render-timeout
  → taxonomy mapping still deferred to F21. Full detail in `build-journal.md`.
- **Feature 08 cleaner built (2026-06-22):** `app/cleaning/cleaner.py`
  `clean(html, *, settings) -> str` — selectolax drops the full boilerplate set
  (`script, style, nav, footer, header, noscript, svg, iframe`), extracts
  `body.text(separator=" ", strip=True)` (falls back to `tree.text()` when bodyless), and
  truncates to `settings.max_content_chars` (**documented lossy**; chunking is Phase-5).
  **Pure & sync** — no network/job-state/LLM, no `httpx`/`playwright`. Signature takes
  `settings` (not `max_chars`) to match the F14 runner call site. **Phase 1 complete.**
- **Scheduler bounded by concurrency AND atomic admission** (15): `MAX_CONCURRENT_JOBS` semaphore + retained task refs + `try_reserve()` (synchronous check-and-increment, no `await` → no TOCTOU) capping in-flight+waiting at `MAX_QUEUED_JOBS`; over cap → `503`/`429`, no job created; `release()` on terminal / failed-create / failed-submit. Admission **closes first on shutdown** (`try_reserve()` → False), and a `submit()` that fails after reserve+create releases the slot **and** terminalizes the job (no `queued` zombie). Shutdown drains **before** the browser closes.
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 1 — Fetch & Render (complete)
**Last completed:** 08 HTML cleaning & content reduction (2026-06-22)
**Next:** 09 LLM provider interface (Phase 2 — AI Extraction)

**Carry-over into next session:**
- **Phase 1 is done.** The fetch→clean half of the pipeline is built and green
  (112 tests). Next is Phase 2: `app/providers/base.py` `LLMProvider` protocol +
  `ProviderError` (F09), then the Anthropic provider (F10).
- **F08 cleaner is built:** `app/cleaning/cleaner.py` `clean(html, *, settings) -> str`
  — selectolax, drops `_DROP_SELECTOR = "script, style, nav, footer, header, noscript,
  svg, iframe"`, extracts `tree.body.text(separator=" ", strip=True)` (falls back to
  `tree.text()` when bodyless), truncates to `settings.max_content_chars`. **Pure & sync**
  (no network/job-state/LLM; no `httpx`/`playwright`). Naive `text[:cap]` is **documented
  lossy** — token-aware chunking stays a Phase-5 follow-up.
- **Signature is `clean(html, *, settings)`, not `max_chars`** (architect decision): matches
  the canonical F14 runner call site (`clean(fetched.html, settings=settings)`) and every
  other pipeline fn. The F14 runner consumes the cleaner this way.
- **`fetch_service.needs_render` vs the cleaner:** both use selectolax but are *separate*
  responsibilities — `needs_render` (SPA-shell detection, smaller drop set
  `script, style, noscript, template`, `_MIN_VISIBLE_TEXT_CHARS`) is NOT the cleaner (full
  boilerplate strip + cap). Both modules carry a same-named `_DROP_SELECTOR` constant with
  *different* values — intentional, don't merge.
- **F07 render rules (implemented):** matrix in `app/fetching/fetch_service.py`; `_fetch_http`
  retries **only** `TransientFetchError` up to `FETCH_MAX_RETRIES`; render only on
  `render=True` via lazy `browser_manager.get()`. **Playwright `TimeoutError` from render is
  still un-mapped — deferred to F21.** The lifespan wires `app.state.browser_manager` +
  `aclose()`; the **scheduler-drain-then-close** ordering still arrives with F15.
- **Test seams:** patch module attributes (`http_fetcher.fetch` / `browser.render`); all
  tests build `Settings(_env_file=None, …)` so the dev shell can't bleed in; app-level tests
  pin `base_url="http://127.0.0.1"`. Cleaner tests just feed HTML and assert trimmed text.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F08 — `app/cleaning/cleaner.py`,
  `tests/test_cleaner.py` (new).
- **OPEN — pending decision:** F08 not yet committed. Developer was asked "commit F08 now
  or proceed to F09?" and the session ended before answering. Resolve this first next
  session. (Reminder: per CLAUDE.md, commits never add a co-author.)

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
- [ ] 09 LLM provider interface
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

- **Feature 05 HTTP fetch built (2026-06-22):** `app/fetching/models.py` (`FetchResult`
  frozen dataclass + computed `status_ok`/`is_html`) + `app/fetching/http_fetcher.py`
  (`fetch(url, *, settings, transport=None)`): **`await`**s the async guard, **pins the
  vetted IP** (IP-in-URL + `Host` header + `extensions={"sni_hostname": host}`), manual
  per-hop redirect re-pin (≤ `max_redirects`; relative `Location` via `urljoin` on the
  *logical* URL), **hard streamed byte cap** before buffering. New `TransientFetchError`
  for timeout/connection (retryable); non-2xx is **returned**, not raised. Tests inject
  `httpx.MockTransport` via the `transport` seam. Full detail in `build-journal.md`.
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

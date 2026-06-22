# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 1 — Fetch & Render
**Last completed:** 07 Fetch strategy / render decision (2026-06-22)
**Next:** 08 HTML cleaning & content reduction

**Carry-over into next session:**
- **The lifespan now owns the browser.** `app/main.py` wires
  `app.state.browser_manager = BrowserManager(settings)` and `await ...aclose()` in the
  shutdown `finally` (no-op if never launched). The **scheduler-drain-then-close** ordering
  still arrives with F15 (the drain must run *before* `aclose()`). The F06 deferral is done.
- **F08 builds `app/cleaning/cleaner.py`** `clean(html, *, settings)` (or `max_chars`):
  selectolax — drop `script/style/nav/footer/header/svg/iframe`, then truncate to
  `MAX_CONTENT_CHARS`. **Documented lossy** (naive `text[:cap]`); token-aware chunking is a
  Phase-5 follow-up, not a silent TODO. Pure function: HTML in → trimmed text out — **no**
  network, job state, or LLM. **`app/cleaning` must not import `httpx`/`playwright`.**
- **`fetch_service.needs_render` already uses selectolax**, but it is a *separate*
  responsibility (SPA-shell detection) from the cleaner (strip + cap) — don't merge them.
  Its threshold is the module constant `_MIN_VISIBLE_TEXT_CHARS` (no env var).
- **F07 render rules (now implemented):** matrix in `app/fetching/fetch_service.py`;
  `_fetch_http` retries **only** `TransientFetchError` up to `FETCH_MAX_RETRIES` (SSRF/oversize
  propagate, never retried); render runs only on `render=True` via lazy `browser_manager.get()`
  (so `render=False` never launches Chromium); a rendered result is re-checked for 2xx+HTML.
  **Playwright `TimeoutError` from render is left un-mapped — still deferred to F21.**
- **Test seams:** fetch_service tests patch the `http_fetcher.fetch` / `browser.render`
  module attributes + a `_FakeBrowserManager` whose `get()` records calls (asserts the browser
  is never requested on `render=False`). HTTP-fetcher tests still use `httpx.MockTransport` +
  the `url_guard._resolve` seam. All construct `Settings(_env_file=None, allow_private_hosts=…)`
  so the dev shell can't bleed in; app-level tests pin `base_url="http://127.0.0.1"`.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F07 — `app/fetching/fetch_service.py`,
  `tests/test_fetch_service.py` (new); `app/main.py`, `tests/test_main.py` (modified). Still
  pending from F06 — `app/fetching/browser.py`, `tests/test_browser.py`,
  `tests/test_browser_integration.py` (new); `.github/workflows/ci.yml` (modified).

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
- [ ] 08 HTML cleaning & content reduction

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

- **Feature 04 SSRF guard built (2026-06-22):** `app/fetching/url_guard.py` (`validate` /
  `resolve_and_validate`) + `app/fetching/errors.py` (`FetchError`, `SSRFError(FetchError)`).
  Both functions are **`async`** (`await loop.getaddrinfo` — never blocks the loop);
  **validate-all/pin-first** (any blocked resolved IP rejects the URL, first vetted IP is
  pinned); IPv4-mapped IPv6 unwrapped; `ALLOW_PRIVATE_HOSTS=true` disables only the IP
  block (scheme allow-list always applies). The HTTP-pin / opt-in-render spec rationale is
  in `architecture.md` and archived in `build-journal.md`. Full detail in `build-journal.md`.
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
- **Scheduler bounded by concurrency AND atomic admission** (15): `MAX_CONCURRENT_JOBS` semaphore + retained task refs + `try_reserve()` (synchronous check-and-increment, no `await` → no TOCTOU) capping in-flight+waiting at `MAX_QUEUED_JOBS`; over cap → `503`/`429`, no job created; `release()` on terminal / failed-create / failed-submit. Admission **closes first on shutdown** (`try_reserve()` → False), and a `submit()` that fails after reserve+create releases the slot **and** terminalizes the job (no `queued` zombie). Shutdown drains **before** the browser closes.
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 1 — Fetch & Render
**Last completed:** 06 Browser render (fallback) (2026-06-22)
**Next:** 07 Fetch strategy / render decision

**Carry-over into next session:**
- **F06 deferred the lifespan wiring to F07 (a planning decision).** `BrowserManager` +
  `render()` exist in `app/fetching/browser.py`, but `app.state.browser_manager` is **not**
  wired — `app/main.py` is untouched except a one-word comment pointing the wiring at F07.
  **F07 must:** add `app.state.browser_manager = BrowserManager(get_settings())` in the
  lifespan and `await app.state.browser_manager.aclose()` on shutdown (a no-op if never
  launched; the scheduler-drain-then-close ordering arrives with F15). F07 also gives us the
  app-level "HTTP-only never launches Chromium" check that F06 only asserts at the unit level.
- **F07 builds `fetch_service.fetch(url, *, browser_manager, render=False)` + `needs_render()`**
  implementing the architecture **fallback matrix**. Call `render()` only in the `render=True`
  branch, after fetching the live browser lazily via `await browser_manager.get()` — never
  launch Chromium on the default (`render=False`) path.
- **`render()` does NOT map a Playwright `goto` timeout into the taxonomy** — it lets the
  Playwright `TimeoutError` propagate (only over-cap → `FetchError`, blocked → `SSRFError`,
  non-2xx → returned `FetchResult`). Wrapping render timeouts into a readable job error is
  **deferred to F21** (timeouts/retries). F07's matrix retries the HTTP path's
  `TransientFetchError`, not render failures.
- **Real-browser tests skip gracefully when Chromium is absent.** `tests/test_browser.py`
  is fully mocked (no binary); `tests/test_browser_integration.py` launches a real Chromium
  against a loopback `ThreadingHTTPServer` fixture and `pytest.skip`s if the binary is
  missing. **CI now runs `playwright install --with-deps chromium`** so it runs there;
  locally run `uv run playwright install chromium` once (the binary IS installed in this
  workspace now — the integration test passed for real).
- **The integration test uses `allow_private_hosts=True`** — the documented SSRF escape hatch
  is required so the guard permits the `127.0.0.1` fixture. Production default stays `False`.
- **Mock the Playwright surface with small fakes, not a real browser**, mirroring the
  `httpx.MockTransport` / `url_guard._resolve` seam style; `BrowserManager` is driven by
  patching `app.fetching.browser.async_playwright`.
- **Tests inject `httpx.MockTransport`** on `http_fetcher.fetch`; DNS goes through the
  `url_guard._resolve` seam. Tests pin `allow_private_hosts` explicitly so the dev shell
  can't bleed in. App-level tests pin `base_url="http://127.0.0.1"` (TrustedHost rejects the
  default `testserver` Host). `ALLOWED_HOSTS` needs `NoDecode` + before-validator for CSV.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** `app/fetching/browser.py`, `tests/test_browser.py`,
  `tests/test_browser_integration.py` (new); `.github/workflows/ci.yml`, `app/main.py` (modified).

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
- [ ] 07 Fetch strategy / render decision
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
- **Scheduler bounded by concurrency AND atomic admission** (15): `MAX_CONCURRENT_JOBS` semaphore + retained task refs + `try_reserve()` (synchronous check-and-increment, no `await` → no TOCTOU) capping in-flight+waiting at `MAX_QUEUED_JOBS`; over cap → `503`/`429`, no job created; `release()` on terminal / failed-create / failed-submit. Admission **closes first on shutdown** (`try_reserve()` → False), and a `submit()` that fails after reserve+create releases the slot **and** terminalizes the job (no `queued` zombie). Shutdown drains **before** the browser closes.
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Feature 03 app skeleton (2026-06-22):** `create_app()` + **minimal deferred lifespan** (settings + logging only; `job_store`/`browser_manager`/`scheduler` deferred to F13/F06/F15 as a comment, no stubs); `TrustedHostMiddleware(ALLOWED_HOSTS)` is the live v1 Host allow-list; `python -m app` honors `HOST`/`PORT`; `SettingsDep` added to `config.py`; `/health` is liveness-only with an inline `HealthResponse`. Full detail in `build-journal.md`.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

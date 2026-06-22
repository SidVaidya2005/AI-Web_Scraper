# Build Journal

> **Role:** Full archive of build decisions, gotchas, and verification results, organized by feature.
> **Write to after every completed feature.** When `progress-tracker.md` "Key Decisions" exceeds ~10 bullets, prune the older/lower-stakes ones here.
> **Relates to:** mirrors the feature order in `build-plan.md`.

<!-- Entry format — repeat per completed feature:

## Phase {{N}} · Feature {{NN}} — {{FEATURE_NAME}}  *(YYYY-MM-DD)*
- Decision: …
- Gotcha: …
- Verified: …

-->

## Phase 0 · Feature 01 — Project scaffold & tooling  *(2026-06-22)*

**Decisions:**
- **Scaffold depth = package skeleton only.** Created `app/` + every subpackage dir
  with just `__init__.py` (each carrying a one-line boundary docstring); **no** module
  files — each later feature creates the modules it owns. Honors "build only what the
  feature requires."
- **Python pinned to 3.12** via `.python-version` (local system Python is 3.14.5).
  `uv sync` auto-fetched CPython **3.12.13**. Matches the documented 3.12+ target and
  avoids bleeding-edge wheel gaps for C-extension deps (selectolax, playwright) on 3.14.
- **One smoke test** (`tests/test_smoke.py::test_app_package_imports`) — pytest exits
  with **code 5 ("no tests collected")** on zero tests, which would fail CI; one real
  test makes pytest exit 0.
- **Build backend = hatchling**, `packages = ["app"]`, so `uv sync` installs `app`
  editable → `import app` and `uvicorn app.main:app` resolve in the venv and CI
  (flat layout, no `src/`).
- **Dependency layout:** runtime deps in `[project.dependencies]`; `ruff` / `pytest` /
  `pytest-asyncio` in `[dependency-groups] dev`. Minimal floors only (`pydantic>=2`);
  the committed `uv.lock` is the exact-pin source of truth.
- **Tooling config:** ruff `target-version = "py312"`, `lint.select = ["E","F","I","UP","B"]`;
  pytest `asyncio_mode = "auto"`, `testpaths = ["tests"]`.
- **CI:** single GitHub Actions workflow on push + PR — `uv sync --frozen` → `ruff check`
  → `ruff format --check` → `pytest`; `astral-sh/setup-uv@v5` reads `.python-version`.
  **No** Playwright Chromium install yet (deferred to Feature 06 — first render tests).
- **`.gitignore` and README were already complete** from prior commits — not regenerated.
- **`MAX_CONTENT_CHARS=50000`** chosen as a provisional `.env.example` default (the
  code-standards table gives no number); Feature 02 finalizes the authoritative
  `Settings` default.

**Gotchas:**
- pytest exit-code **5** on an empty suite would fail CI — fixed by the smoke test.
- First sync must be plain `uv sync` (generates `uv.lock`); CI uses `uv sync --frozen`
  for reproducibility — verified consistent ("Checked 60 packages", no drift).
- Notable resolved pins (in `uv.lock`): ruff 0.15.18, pytest 9.1.1, pytest-asyncio
  1.4.0, pydantic 2.13.4, pydantic-settings 2.14.2, playwright 1.60.0, starlette 1.3.1,
  uvicorn 0.49.0, anthropic, openai 2.43.0, selectolax 0.4.10, jsonschema 4.26.0.

**Verified:**
- `uv run python --version` → 3.12.13; `uv.lock` generated; `import app` OK.
- `ruff check .` → All checks passed; `ruff format --check .` → 11 files already formatted.
- `pytest` → **1 passed**, exit 0.
- `uv sync --frozen` → consistent (no lockfile drift).
- `.env.example` covers all 26 documented vars; defaults satisfy the future invariant
  `MAX_CONCURRENT_JOBS (4) <= MAX_QUEUED_JOBS (50) <= MAX_JOBS (500)`.
- CI workflow is valid YAML with the four gates; green run to be confirmed after the
  first push (commit/push only on request).

---

## Phase 0 · Feature 02 — Config & settings  *(2026-06-22)*

**Built:** `app/config.py` (`Settings(BaseSettings)` with all 26 documented env vars +
cached `get_settings()`); `tests/test_config.py` (7 tests).

**Decisions:**
- **`MAX_CONTENT_CHARS = 50000`** is the authoritative `Settings` default (was provisional
  in `.env.example`, which already matched — left unchanged).
- **API-key presence is NOT validated in `Settings`.** Keys are read as `SecretStr` (may be
  empty); the registry/provider (Feature 10) errors if the active provider's key is missing.
  Rationale: keeps F02 scoped to relationships per the build-plan, and `/health` (liveness)
  + keyless tests must run without provider keys (`architecture.md`).
- **Literal + SecretStr typing.** `LLM_PROVIDER` / `LOG_LEVEL` are `Literal` (bad value fails
  at construction); `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` are `SecretStr` (no leak in
  logs/reprs). Provider code reads keys via `.get_secret_value()` in F10.
- **Positivity via `Field` constraints, relationship via `model_validator`.** Per-field
  `gt=0` (timeouts, byte/char caps, `MAX_REDIRECTS`, job caps, `port`, `rate_limit`,
  `job_ttl`) and `ge=0` (`fetch_max_retries`, `render_settle_ms`, `shutdown_grace_seconds`);
  a single `@model_validator(mode="after")` enforces
  `max_concurrent_jobs <= max_queued_jobs <= max_jobs`. Both fail fast at construction.
- **`SettingsDep` deferred to Feature 03.** Defining the FastAPI alias
  `Annotated[Settings, Depends(get_settings)]` now would import FastAPI into `config.py` for
  something no handler consumes yet — deferred to where it's first used (scope discipline).

**Gotchas:**
- **`ALLOWED_HOSTS` CSV vs. pydantic-settings JSON decode.** A `list[str]` field auto-attempts
  JSON-decoding of its raw env value, so `127.0.0.1,localhost` fails as invalid JSON *before*
  any validator runs. Fix (confirmed via Context7 `/pydantic/pydantic-settings`):
  `Annotated[list[str], NoDecode]` (surgical, per-field — not a global `enable_decoding=False`)
  plus a `@field_validator(mode="before")` that splits on `,` and strips. Same treatment
  required for any future `list`/complex setting.
- **Test isolation:** tests construct `Settings(_env_file=None)` so a real `.env` can't bleed
  in, and `delenv` the asserted-default vars so a value in the dev shell can't either. The
  cache-identity test brackets `get_settings()` with `cache_clear()` in a `finally`.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 13 files formatted.
- `uv run pytest -q` → **8 passed** (7 config + 1 smoke), exit 0.
- Confirmed by test: defaults applied; env overrides read incl. CSV `ALLOWED_HOSTS` split;
  `MAX_QUEUED_JOBS < MAX_CONCURRENT_JOBS` and `FETCH_TIMEOUT_SECONDS=0` each raise
  `ValidationError` at construction; bad `LLM_PROVIDER` enum rejected; `SecretStr` masks the
  key in `repr`/`str` and exposes it only via `get_secret_value()`; `get_settings()` cached.
- No env access added outside `app/config.py` (invariant preserved).

---

## Phase 0 · Feature 03 — App skeleton + health endpoint  *(2026-06-22)*

**Built:** `app/main.py` (`create_app()` factory + `lifespan` + module-level `app`);
`app/logging.py` (`configure_logging`); `app/api/health.py` (`GET /health`);
`app/__main__.py` (`python -m app` entry point); `SettingsDep` added to
`app/config.py`; `tests/test_main.py` (4 tests).

**Decisions:**
- **Minimal deferred lifespan.** Lifespan only loads settings, configures logging,
  and stashes `app.state.settings`; `job_store` (F13) / `browser_manager` (F06) /
  `scheduler` (F15) are left as a documented comment, **not** stub modules — same
  scope discipline as F02 deferring `SettingsDep`. The comment also records the
  drain-before-close shutdown ordering those will need.
- **`SettingsDep` lives in `app/config.py`** (`Annotated[Settings, Depends(get_settings)]`)
  even though `/health` is settings-free — config is its canonical home and F03 is the
  first FastAPI-aware feature. This pulls `from fastapi import Depends` into `config.py`
  (acceptable: it reads no env, so the env-only invariant holds).
- **Logging targets the `app` logger namespace** (children `app.<area>` inherit a
  single handler/level), configured once in `create_app()`, idempotent (no duplicate
  handlers across repeated `create_app()` in tests), `propagate=False`.
- **`/health` is liveness-only** with an inline `HealthResponse` `response_model`,
  kept out of `app/models.py` (reserved for shared extract/job models).
- **`TrustedHostMiddleware` from `starlette.middleware.trustedhost`** with
  `settings.allowed_hosts` — the live v1 DNS-rebinding Host allow-list.
- **`__main__` uses the import-string form** `uvicorn.run("app.main:app", …)`; no
  `--reload` (dev reload stays the documented `uvicorn app.main:app --reload` command).

**Gotchas:**
- **TestClient's default Host is `testserver`**, which `TrustedHostMiddleware` rejects
  (400). App-level tests pin `base_url="http://127.0.0.1"` (allow-listed); a separate
  test asserts a disallowed Host (`evil.com`) → 400, proving the middleware is live.
- **Testing `__main__` without binding a socket:** `monkeypatch` `uvicorn.run` and assert
  it received `host=settings.host` / `port=settings.port`, compared to the cached
  `get_settings()` so the assertion is env-independent.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 18 files formatted.
- `uv run pytest -q` → **12 passed** (8 prior + 4 new), exit 0.
- Lifespan boots/shuts cleanly via the TestClient context; `/health` → `200 {"status":"ok"}`;
  disallowed Host → `400`; `__main__` forwards `settings.host`/`port` to uvicorn.
- One benign warning (Starlette deprecation re: `httpx` in TestClient) — a dep-version
  note from the environment, not introduced by this feature.

---

## Phase 1 · Feature 04 — URL safety & SSRF guard  *(2026-06-22)*

**Built:** `app/fetching/errors.py` (`FetchError(RuntimeError)`, `SSRFError(FetchError)`);
`app/fetching/url_guard.py` (`validate` / `resolve_and_validate`, pure `_is_blocked`,
async `_resolve`); `tests/test_url_guard.py` (24 tests). No new dependencies — stdlib
`ipaddress` / `urllib.parse` / `asyncio` / `socket`.

**Decisions:**
- **Async DNS resolution.** Both `validate` and `resolve_and_validate` are `async def`;
  `_resolve` uses `await loop.getaddrinfo(...)` so a slow lookup never stalls the event
  loop (concurrent jobs + dashboard polling). The sync call examples in `library-docs.md`
  (httpx / browser) pick up a one-word `await` in F05/F06.
- **Validate-all, pin-first.** Every resolved A/AAAA record is classified; a single
  blocked address rejects the whole URL; the first vetted address is returned for
  pinning. Closes the public+private multi-record bypass.
- **`validate` is a thin wrapper** over `resolve_and_validate` (one classification path).
- **Error taxonomy:** `SSRFError(FetchError)` — guard rejections are `SSRFError`, but
  `except FetchError` (browser route handler) still catches them; bad scheme / missing
  host / DNS failure raise the base `FetchError`.
- **`ALLOW_PRIVATE_HOSTS=true` disables only the IP block** (the test/owned-LAN escape
  hatch); the scheme allow-list always applies.
- **Test file is `tests/test_url_guard.py`** (the project's actual test-per-module
  convention), not the coarse `tests/test_fetching.py` from the architecture tree.

**Gotchas:**
- **IPv4-mapped IPv6** (`::ffff:127.0.0.1`) must be unwrapped via `ip.ipv4_mapped` before
  classification, or a loopback target slips through as a "public" v6 address.
- **The `gaierror`→`FetchError` mapping lives inside `_resolve`**, so a test that
  monkeypatches `_resolve` can't exercise it — that one test patches the running loop's
  `getaddrinfo` directly; every other test patches the `_resolve` seam to avoid real DNS.
- `_settings()` pins `allow_private_hosts` explicitly so a dev-shell `ALLOW_PRIVATE_HOSTS`
  can't bleed into assertions (same isolation pattern as `test_config.py`).

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` clean.
- `uv run pytest -q` → **36 passed** (12 prior + 24 new), exit 0.
- Confirmed: non-http schemes + missing host → `FetchError`; blocked IP literals (v4, v6,
  IPv4-mapped, metadata `169.254.169.254`, `0.0.0.0`) → `SSRFError`; public literal/
  hostname pass and pin; rebinding-style (public host → private IP) and multi-IP-with-one-
  private → `SSRFError`; all-public multi-IP pins the first; escape hatch permits private
  but still enforces scheme; `gaierror` → `FetchError`; `SSRFError` caught by `except FetchError`.

---

## Phase 1 · Feature 05 — HTTP fetch (fast path)  *(2026-06-22)*

**Built:** `app/fetching/models.py` (`FetchResult` frozen dataclass + computed
`status_ok`/`is_html`); `app/fetching/http_fetcher.py` (`fetch(url, *, settings,
transport=None)`); `TransientFetchError(FetchError)` added to `app/fetching/errors.py`;
`tests/test_fetch_models.py` (19 tests) + `tests/test_http_fetcher.py` (11 tests). No new
dependencies — `httpx` was already in the stack.

**Decisions:**
- **Transient failures get their own type.** `TransientFetchError(FetchError)` is raised for
  httpx timeouts/connection failures (retryable); oversize/too-many-redirects stay plain
  `FetchError`; SSRF stays `SSRFError`. Gives F07/F21 a clean retry-then-render vs hard-fail
  signal in the layer that raises it.
- **Non-2xx is returned, not raised.** A 4xx/5xx comes back as a `FetchResult` (per the F07
  fallback matrix); only timeout/connection/too-many-redirects/size-cap/SSRF raise.
- **`FetchResult` = 5 data fields + computed `status_ok`/`is_html`.** The two properties are
  pure functions already referenced by the architecture data-flow / F07 matrix, keeping that
  matrix declarative. `is_html` treats an empty/missing content-type leniently as HTML.
- **Test seam = optional `transport` param** → `httpx.MockTransport`; no new dep (no respx),
  prod path unchanged. `httpx.AsyncClient(transport=None)` already falls back to the default
  transport, so no conditional-kwargs plumbing was needed.
- **Pinning realized exactly per `library-docs.md` → httpx:** `resolve_and_validate` →
  IP-in-URL via `copy_with(host=ip)`, `Host` header = original host (+ port if non-default),
  `extensions={"sni_hostname": host}`; `follow_redirects=False` with manual per-hop
  re-resolve+re-pin; relative `Location` resolved with `urljoin` against the **logical** URL;
  streamed `aiter_bytes` with a hard pre-buffer cap at `MAX_RESPONSE_BYTES`.

**Gotchas:**
- **Documentation IP ranges are non-global in Python 3.12.** `192.0.2.0/24`,
  `198.51.100.0/24`, `203.0.113.0/24` (TEST-NET) are classified `is_private`/not-global, so
  the guard correctly rejects them. First redirect-repins test used `198.51.100.1`/
  `203.0.113.9` and failed with `SSRFError` — swapped to real public IPs (`93.184.216.34`,
  `1.1.1.1`). The guard was right; the fixture was wrong.
- **The `library-docs.md` httpx example calls the guard without `await`** (the guard went
  async in F04) — added the `await`. F06's browser route handler needs the same.
- **IPv6 pinning:** bracket the literal for the URL host and `Host` header via a small
  `_bracket` helper; httpx accepts the bracketed form in `copy_with` and exposes `.host`
  unbracketed (confirmed by `test_ipv6_pinned_ip_is_usable`).
- **Simulating transport failures with `MockTransport`:** the handler can `raise
  httpx.ReadTimeout(...)` / `httpx.ConnectError(...)` (constructed with `request=request`);
  `httpx.TimeoutException` is a subclass of `httpx.TransportError`, so the `except` order is
  TimeoutException first (→ "timed out") then TransportError (→ "failed"), both →
  `TransientFetchError`.
- **API shapes verified against Context7** `/encode/httpx` (sni_hostname extension + Host
  override + MockTransport + async streaming) before writing code, per CLAUDE.md.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → clean.
- `uv run pytest -q` → **66 passed** (36 prior + 19 models + 11 fetcher), exit 0. (One
  pre-existing Starlette/httpx TestClient deprecation warning, unrelated to this feature.)
- Confirmed by test: success returns a populated `FetchResult` and the request hit the
  **pinned IP** with original `Host` + `sni_hostname`; non-2xx returns a `FetchResult`;
  timeout/connect → `TransientFetchError`; oversized → `FetchError` (not transient);
  too-many-redirects → `FetchError`; redirect→metadata → `SSRFError`; redirects re-pin each
  hop; relative `Location` resolves against the logical URL; IPv6 pinned IP works.
- Invariants held: `httpx` imported only in `app/fetching/`; no env access outside
  `app/config.py`; no browser/render code introduced (scope held to the fast path).

---

## Phase 1 · Feature 06 — Browser render (fallback)  *(2026-06-22)*

**Built:** `app/fetching/browser.py` (`BrowserManager` + `render(url, *, browser,
settings) -> FetchResult`); `tests/test_browser.py` (14 mock-based unit tests);
`tests/test_browser_integration.py` (1 gated real-Chromium test); a
`playwright install --with-deps chromium` step added to `.github/workflows/ci.yml`. No
new dependencies (`playwright` was already in the stack); no new exception types.

**Decisions:**
- **Test strategy = hybrid, CI runs real** (architect decision). All of *our* logic
  (lazy launch, guard routing, WS block, byte caps, real-metadata `FetchResult`) is
  covered by fully-mocked unit tests with no browser, mirroring the existing
  `httpx.MockTransport` / `url_guard._resolve` seam style. One real-Chromium integration
  test proves *post-JS content actually renders* against a loopback
  `ThreadingHTTPServer` fixture, and a **real** lazy launch via `BrowserManager.get()`.
  CI installs Chromium so it runs there; locally it `pytest.skip`s if the binary is
  absent (suite still green everywhere). F01 had deliberately deferred the Chromium CI
  install to this feature.
- **Lifespan wiring deferred to F07** (architect decision). `app/main.py` is untouched
  apart from a one-word comment pointing the `app.state.browser_manager` wiring at F07.
  Rationale: build/test the modules in isolation here; wire them when F07's
  `fetch_service` is their first real consumer. The app-level "HTTP-only never launches
  Chromium" assertion therefore moves to F07; F06 asserts laziness at the
  `BrowserManager` unit level instead.
- **`render()` uses `url_guard.validate`, not `resolve_and_validate`** — the browser
  can't pin an IP, so only rejection-on-failure is needed (documented residual
  DNS-rebinding risk on this path, per the architecture invariant).
- **No render-timeout taxonomy mapping in F06.** `render()` lets a Playwright `goto`
  `TimeoutError` propagate (over-cap → `FetchError`, blocked → `SSRFError`, non-2xx →
  *returned* `FetchResult`). Wrapping render timeouts into a readable, non-leaky job
  error belongs to F21 (timeouts/retries) — kept out of scope here to honor the plan.
- **Best-effort byte cap** = cumulative `content-length` budget (via
  `context.on("response", …)`) + a post-render `page.content()` size backstop; the HTTP
  fast path keeps the *hard* guarantee.

**Gotchas:**
- **Chromium not installed by default.** Playwright 1.60 package + `route_web_socket`
  were present, but no browser binary and no CI install step. Added
  `uv run playwright install chromium` locally (the integration test then passed for
  real, not skipped) and `--with-deps` to CI for the runner's OS libraries.
- **Ruff split the aliased import.** `from playwright.async_api import TimeoutError as
  PlaywrightTimeoutError` is isort-sorted into its own `from` block by `ruff check
  --fix` — expected, left as-is.
- **A breadcrumb comment in `app/main.py` had to change.** It said
  `browser_manager -> Feature 06`; since wiring is deferred, it now reads `Feature 07`.
  The longer first wording tripped **E501 (92 > 88)** — shortened to `(wire the F06
  BrowserManager)`. (Yes, `app/main.py` was touched — only this comment.)
- **Mocking the budget callback:** the fake `Page.goto` fires the registered
  `context.on("response", …)` callback with fake `content-length` responses so the
  cumulative budget can be exercised deterministically without a browser.
- **API shapes confirmed via Context7** (`/websites/playwright_dev_python`):
  `await context.route_web_socket(pattern, handler)` and `await ws.close(...)` before
  writing code, per CLAUDE.md authority order.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 28 files
  formatted.
- `uv run pytest -q` → **81 passed** (66 prior + 14 mock + 1 integration), exit 0 (one
  pre-existing Starlette/httpx TestClient deprecation warning, unrelated). The
  integration test ran for real (`PASSED`, not `SKIPPED`) — confirmed via `-v`.
- Confirmed by test: lazy launch exactly once under 8 concurrent `get()`; `aclose()`
  no-op when never launched + idempotent + stops the driver when launched; launch
  failure stops the driver and leaves `_browser=None` (retryable); `render()` builds
  real status/content-type/final_url with `mode="browser"`; non-2xx returned not raised;
  blocked top URL raises before any context; route guard aborts blocked / continues
  allowed; all WebSockets closed; `service_workers="block"` set; both byte-cap paths
  raise `FetchError`; context always closed (incl. when `goto` raises); settle timeout
  swallowed; real Chromium renders JS-injected content on a loopback fixture.
- Invariants held: `playwright` imported only in `app/fetching/`; no env access outside
  `app/config.py`; `app/main.py` carries no browser logic (wiring deferred to F07).

---

## Phase 1 · Feature 07 — Fetch strategy / render decision  *(2026-06-22)*

**Built:** `app/fetching/fetch_service.py` (`fetch(url, *, browser_manager, settings,
render=False) -> FetchResult`, `needs_render(html)`, helpers `_fetch_http` /
`_render_and_check` / `_insufficient_message`); lifespan wiring in `app/main.py`
(`app.state.browser_manager` + `aclose()` on shutdown); `tests/test_fetch_service.py`
(23 tests) + 1 new lifespan test in `tests/test_main.py`. No new dependencies (selectolax
was already in the stack); no new exception types.

**Decisions:**
- **`needs_render` = selectolax visible-text threshold** (architect-confirmed). Parse →
  decompose `script, style, noscript, template` → measure `body` text → `True` when empty
  or `< _MIN_VISIBLE_TEXT_CHARS` (200). Dropping script/style first is the whole point: a
  raw-length check is fooled by a big inlined-JS SPA shell, but after stripping scripts that
  shell has ~0 visible text. Threshold is a **module constant, not an env var** — keeps F07
  off the settings contract (architect-confirmed). selectolax in `app/fetching/` is allowed
  (the boundary rules only bar `httpx`/`playwright` from `cleaning`/`extraction`).
- **F07 owns the bounded transient retry** (architect-confirmed; matches the F06 carry-over
  note). `_fetch_http` loops `range(fetch_max_retries + 1)`, retrying **only**
  `TransientFetchError`; `SSRFError`/oversize/too-many-redirects are not transient, so they
  propagate on the first attempt. Render-failure retries stay out (F21).
- **Render-timeout mapping stays deferred to F21.** `fetch_service` does not catch Playwright
  `TimeoutError` from `render` — it propagates un-mapped (a test pins this so the deferral is
  explicit). Only `FetchError`/`SSRFError` from render, and the rendered `FetchResult`'s
  status/content-type, are acted on here.
- **No re-gate after render.** A successful render is the final attempt: any
  `status_ok and is_html` rendered result is returned as-is (no second `needs_render`); a
  rendered non-2xx/non-HTML result becomes a `FetchError`.
- **Module-qualified seams over aliased imports.** `fetch_service` imports the modules
  (`from app.fetching import browser, http_fetcher`) and calls `http_fetcher.fetch(...)` /
  `browser.render(...)`. This avoids shadowing the `render: bool` param and gives tests clean
  `monkeypatch.setattr(http_fetcher, "fetch", …)` / `(browser, "render", …)` seams — the same
  style as the existing `httpx.MockTransport` / `url_guard._resolve` seams.
- **`settings` added to the signature** (build-plan omitted it, but `http_fetcher`/`render`
  need it; `architecture.md`'s own snippet includes it).

**Gotchas:**
- **`SSRFError` is a `FetchError`, not a `TransientFetchError`** — so `except TransientFetchError`
  in both `_fetch_http` and `fetch` correctly lets a blocked URL propagate without a retry and
  without ever reaching the render branch. A test asserts the HTTP fetcher is called exactly
  once for an SSRF rejection even with `render=True`.
- **`assert last_exc is not None` after the retry loop** documents that the loop always runs at
  least once (`fetch_max_retries >= 0`), satisfying the type checker without an unreachable
  branch. The selected ruff rules don't flag possibly-unbound, but the assert reads clearer.
- **Test FetchResults need `> 200` chars of real text to count as "good".** `_RICH_HTML` uses
  `"real words here " * 40` (~640 chars); the SPA fixture is an empty `<div id="root">` plus a
  5000-char `<script>` that collapses to ~0 text after the decompose step.
- **ruff reformatted `tests/test_fetch_service.py`** (collapsed a couple of wrapped calls) —
  applied `ruff format`, no logic change.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 30 files formatted.
- `uv run pytest -q` → **105 passed** (81 prior + 24 new), exit 0 (one pre-existing
  Starlette/httpx TestClient deprecation warning, unrelated).
- Confirmed by test, per the fallback matrix × render flag: 2xx-HTML-with-text → `mode="http"`
  and the browser is **never requested** (both flags); SPA shell → render on `render=True`
  (`mode="browser"`), `FetchError` with the "retry with render=true" hint and **no browser**
  on `render=False`; non-HTML and non-2xx follow the matrix per flag (error carries the
  content-type / HTTP status); transient retried exactly `fetch_max_retries + 1` times, a
  recovering retry returns the HTTP result, exhausted → render (`render=True`) or
  `TransientFetchError` (`render=False`); `SSRFError` propagates without retry or render;
  rendered non-2xx/non-HTML → `FetchError`; render `TimeoutError` propagates un-mapped; render
  `SSRFError` propagates; `needs_render` flags empty/SPA-shell and passes content-rich HTML.
  App level: an HTTP-only lifespan cycle leaves `app.state.browser_manager._browser is None`
  (Chromium never launched) and `aclose()` runs cleanly.
- Invariants held: `playwright` still imported only inside `app/fetching/browser.py` (main.py
  imports the `BrowserManager` class, not playwright); no env access outside `app/config.py`;
  `fetch_service` touches no job state; the browser is launched lazily and only on the render
  path.

---

## Phase 1 · Feature 08 — HTML cleaning & content reduction  *(2026-06-22)*

**Built:** `app/cleaning/cleaner.py` (`clean(html, *, settings) -> str`);
`tests/test_cleaner.py` (7 tests). No new dependencies (selectolax was already in the
stack and already used by `fetch_service.needs_render`); no new exception types. Closes
Phase 1.

**Decisions:**
- **Signature is `clean(html, *, settings: Settings)`, not `clean(html, *, max_chars)`**
  (architect session, developer-confirmed). The project's own docs split on this:
  `build-plan.md` F08 and `library-docs.md` write `max_chars`; `code-standards.md`'s example
  and the documented F14 runner call site (`content = clean(fetched.html, settings=settings)`)
  write `settings`. Chose `settings` for consistency — every other pipeline function
  (`http_fetcher.fetch`, `browser.render`, `fetch_service.fetch`) already takes `*, settings`,
  and the canonical consumer (the F14 runner) calls it that way. Reads
  `settings.max_content_chars` internally.
- **Returns plain text, not cleaned HTML.** `tree.body.text(separator=" ", strip=True)` with a
  fallback to `tree.text()` when there is no `<body>` (fragments / malformed input). The LLM
  gets text; both doc examples return text.
- **Synchronous, pure function.** No `async` — it is pure CPU (selectolax parse), no I/O,
  matching both doc examples and the sibling `needs_render`. The architecture's
  `run_in_executor` offload note is a future concern, not needed for v1. Same input → same output.
- **Naive `text[:max_content_chars]` truncation, documented lossy.** Overflow is dropped;
  token-aware budgeting / chunk-and-merge stays a Phase-5 follow-up (F23), not a silent TODO.
- **Drop set is the *full* boilerplate set** `_DROP_SELECTOR = "script, style, nav, footer,
  header, noscript, svg, iframe"` (a module constant). This is a **different** constant from
  `fetch_service._DROP_SELECTOR` (`"script, style, noscript, template"`): the cleaner strips
  all chrome to maximize signal, while `needs_render` only strips scripts to *measure* visible
  text for SPA detection. Same name, different module, different value — intentional; not merged.
- **Test file is `tests/test_cleaner.py`** (the project's actual test-per-module convention,
  e.g. `test_url_guard.py`, `test_fetch_service.py`), not the coarse `tests/test_cleaning.py`
  from the architecture tree — consistent with the F04 decision to deviate the same way.

**Gotchas:**
- **selectolax/lexbor auto-wraps fragments in a document**, so `tree.body` is rarely `None`
  even for bare-fragment or empty-string input (empty string → an empty `<body>` → `""`). The
  `else tree.text()` fallback is a safety net for genuinely bodyless trees rather than a
  commonly hit branch; the fragment test asserts the **contract** (returns the text, never
  raises) rather than which branch runs, to stay non-brittle against parser internals.
- The drop happens **before** text extraction (`decompose()` then `.text()`) — extracting first
  would leave script/style text in the output.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 32 files formatted.
- `uv run pytest -q` → **112 passed** (105 prior + 7 new), exit 0 (one pre-existing
  Starlette/httpx TestClient deprecation warning, unrelated).
- Confirmed by test: every boilerplate marker (script/style/nav/header/footer/noscript/svg/
  iframe) is absent from the output while real article content survives; output is truncated to
  exactly `max_content_chars` when over the cap and returned intact when under; edge whitespace
  is stripped; empty and whitespace-only HTML return `""` without raising; a bodyless fragment
  still yields its text.
- Invariants held: `app/cleaning/cleaner.py` imports only `selectolax` + `app.config` — no
  `httpx`/`playwright`, no network, no job state, no LLM, no `os`/env access (settings injected).

---

## Phase 2 · Feature 09 — LLM provider interface  *(2026-06-22)*

**Built:** `app/providers/base.py` (`ProviderError(RuntimeError)` + a `@runtime_checkable`
`LLMProvider` Protocol with one async, keyword-only `extract(*, content, prompt,
json_schema) -> dict[str, Any]`); `tests/test_providers.py` (4 tests). No new dependencies
(stdlib `typing` only); no SDK touched. Opens Phase 2.

**Decisions:**
- **`Protocol`, not `ABC`** — concrete providers (F10 Anthropic, F22 OpenAI, test fakes)
  conform structurally, never by inheritance. Matches the canonical `architecture.md` snippet
  and the build-plan wording ("protocol").
- **`@runtime_checkable`** (architect session, developer-confirmed) so the test has a concrete
  runtime assertion: `isinstance(fake, LLMProvider)` plus a non-conforming `object()` failing
  it. Documented caveat: `@runtime_checkable` `isinstance` only verifies *method presence*, not
  signature/async-ness — the real conformance proof is the awaited `extract()` returning a
  `dict`, backed by static type-checking. Both are exercised.
- **Scope held to the contract.** `base.py` carries **only** the Protocol + `ProviderError` —
  no registry, no Anthropic/OpenAI code, no `__init__` re-export (no barrel modules, per
  `code-standards.md`). Those arrive in F10. `app/providers/__init__.py` left as its docstring.
- **`ProviderError(RuntimeError)`** with a one-line docstring — mirrors the established
  error-class house style in `app/fetching/errors.py` (`FetchError` et al.).
- **`extract` signature is fixed by the docs** — keyword-only, async, returns the object
  envelope `dict[str, Any]`; no timeout / provider-selection param here (those are F10/F21).
- **Test file is `tests/test_providers.py`** (test-per-module convention, consistent with the
  F04/F08 deviations from the architecture tree's coarse `test_extraction.py`).

**Gotchas:**
- None of note — pure-stdlib interface feature. The Protocol method body is `...` (no
  implementation), so there is nothing to mock or seam here; the SDK seam work lands in F10.
- The async test needs no explicit marker — `pytest-asyncio` runs in `auto` mode (set in F01).

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 34 files formatted.
- `uv run pytest -q` → **116 passed** (112 prior + 4 new), exit 0 (one pre-existing
  Starlette/httpx TestClient deprecation warning, unrelated).
- Confirmed by test: a structurally-conforming fake is `isinstance(..., LLMProvider)`; a bare
  `object()` is **not**; `extract(...)` awaits to a `dict`; `ProviderError` is a `RuntimeError`
  subclass and is raisable/catchable with its message intact.
- Invariants held: no `anthropic`/`openai` import anywhere (this feature adds none); `base.py`
  imports only stdlib `typing`; no env/`os` access outside `app/config.py`; no registry or
  concrete provider introduced (scope held to the interface).

**Bookkeeping note:** the prior "F08 not yet committed" OPEN item in the tracker was **stale** —
git history shows F08 landed as commit `27097ed 1.8-HTML-cleaning-&-content-reduction`. Only F09
is uncommitted going into the next session.

---

## Phase 2 · Feature 10 — Anthropic provider  *(2026-06-22)*

**Built:** `app/providers/anthropic_provider.py` (`AnthropicProvider`); `app/providers/registry.py`
(`get_provider`); extended `tests/test_providers.py` (+11 tests). First feature to import an LLM
SDK (`from anthropic import AsyncAnthropic`). No new dependencies (`anthropic` already in the
lockfile); no new env vars (all settings existed from F02); no changes to `base.py`/`config.py`.

**Decisions** (architect session, developer-confirmed — plan
`~/.claude/plans/feature-10-anthropic-declarative-feather.md`):
- **Strict normalization deferred to F11.** The provider sets `tool["strict"] = True` whenever
  `json_schema is not None` and passes the schema through **unchanged** — no
  `additionalProperties:false`/`required` normalization here. The two context docs conflicted
  (build-plan F11 lists normalization as F11's job; architecture/library-docs call it a
  "provider-side normalizer"); resolved in favour of build-plan's split to keep F10 thin. F11's
  `extraction/schemas.py` owns normalization, and the F12 engine normalizes before calling the
  provider. The latent "strict on an un-normalized schema would 400" is harmless: the suite mocks
  the SDK and F11 lands before the real API is ever called.
- **Registry takes `override` now; `ProviderError` for openai/unknown.**
  `get_provider(settings, *, override=None)` → `name = override or settings.llm_provider`; only
  `"anthropic"` wired. The override seam exists now (F12 passes `request.provider`); F22 adds the
  `"openai"` branch. Empty `ANTHROPIC_API_KEY` → `ProviderError("ANTHROPIC_API_KEY not configured")`
  at selection (config deliberately doesn't validate key presence — F02 decision).
- **`LLM_TIMEOUT_SECONDS` wired into the client now** (`AsyncAnthropic(api_key=, timeout=)`) — a
  one-line constructor arg that belongs with the client; F21 still owns retries and the
  timeout→job-error taxonomy.
- **Provider takes plain values, not `Settings`** — `AnthropicProvider(*, api_key, model, timeout,
  client=None)`. The registry is the only place that reads `Settings` and unwraps the `SecretStr`
  (`.get_secret_value()`), preserving env-only-in-config and making the provider trivially testable.
- **Test seam = injected client** (mirrors `http_fetcher`'s `transport` seam): optional `client`
  param defaulting to a real `AsyncAnthropic`; tests pass a fake whose `messages.create` is an
  async stub. SDK never hit in the suite.
- **Per-call construction, no caching** (F10): a new `AsyncAnthropic` per `get_provider` call is
  fine for a single-process localhost tool. Provider/client caching + lifecycle is a noted F21+
  follow-up, not a silent gap. `max_tokens=4096` module constant (no `MAX_TOKENS` setting; API
  requires it); no `thinking` config (a forced-tool extraction needs none).

**Gotchas:**
- **API shape confirmed via the `claude-api` skill** before coding (per CLAUDE.md): `AsyncAnthropic`,
  forced tool-use is current, `strict` goes on the **tool** (not `tool_choice`), `max_tokens`
  required, SDK `timeout` is in **seconds**. Anthropic recommends adaptive thinking for hard tasks,
  but a forced-tool extraction needs none — omitted.
- **Generic-error assertion:** the SDK-error test raises `RuntimeError("secret /path... leaked")`
  and asserts the `ProviderError` message is exactly `"LLM provider request failed"` and contains
  no `"secret"` — proving `str(exc)` never leaks into the user-facing message (full detail goes to
  `logger.exception`).
- **Settings isolation:** tests build `Settings(_env_file=None, anthropic_api_key="test-key", …)`.
  pydantic-settings ranks **init kwargs above env vars**, so a pinned field is authoritative even
  if the dev shell exports `ANTHROPIC_API_KEY` — no `delenv` needed for pinned fields.
- **Registry tests need no SDK mock:** constructing a real `AsyncAnthropic` with a dummy key makes
  no network call (the httpx client is lazy), so those tests construct real providers and assert
  type + `provider._model == settings.anthropic_model`.
- **One E501** (89>88) in a test call — wrapped the args; ruff then clean.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 36 files formatted.
- `uv run pytest -q` → **127 passed** (116 prior + 11 new), exit 0 (one pre-existing
  Starlette/httpx TestClient deprecation warning, unrelated).
- Confirmed by test (SDK mocked, no live LLM): forced-tool response → result dict from
  `tool_use.input`; `strict: true` present iff a schema is supplied (and the schema is passed
  through unchanged) and absent otherwise; the call carries `_SYSTEM`, the `<page_content>`
  delimiter, the forced `tool_choice`, and the model from settings; an SDK exception → generic
  `ProviderError` (no `str(exc)` leak); a no-`tool_use` response → `ProviderError`; registry
  returns `AnthropicProvider` for anthropic, raises `ProviderError` for openai/unknown and for an
  empty key.
- Invariants held (grep-verified): `anthropic` imported **only** in
  `app/providers/anthropic_provider.py`; no `os`/env access outside `app/config.py`; model id from
  settings, never a literal; `ProviderError` the single surfaced failure type.

---

## Archived spec decisions  *(pruned from progress-tracker.md "Key Decisions", 2026-06-22)*

_Pre-code decisions from the 2026-06-21 context review, moved here to keep the tracker's
Key Decisions near ~10. The authoritative versions live in `architecture.md` /
`library-docs.md`._

- **Render uses `domcontentloaded` + bounded settle**, never `networkidle` (which can
  hang on long-polling/analytics pages).
- **HTMX polling stops via HTTP `286`** when all jobs are terminal/empty, and **restarts**
  because the submit response re-arms the `every 2s` trigger; the dashboard submit uses a
  form-encoded handler, not the JSON API route.
- **Provider errors are generic & user-safe** (full detail logged, never interpolated into
  `ProviderError`); `MAX_CONTENT_CHARS` is a lossy char cap (chunking is a Phase-5 follow-up).
- **Schema conformance = provider `strict` + post-validation** (pruned 2026-06-22):
  forcing the tool only guarantees it is *called*; the returned dict is re-validated
  against the request `output_schema` in `app/extraction/` regardless. (Authoritative
  in `architecture.md` / `library-docs.md`.)
- **SSRF guard design spec** (pruned 2026-06-22, now implemented in F04): the HTTP path
  **pins the validated IP per request** (IP-in-URL + `Host` header + `sni_hostname`),
  closing the resolve→connect race, with a hard streamed byte cap; the browser path
  guards every connection (`context.route` + `service_workers="block"` +
  `route_web_socket` blocking all WS) but **can't pin**, so it carries a documented
  residual rebinding risk and a best-effort byte cap. Therefore **rendering is opt-in**
  (`render`, default off) and Chromium launches lazily on first render. Authoritative in
  `architecture.md` / `library-docs.md`.

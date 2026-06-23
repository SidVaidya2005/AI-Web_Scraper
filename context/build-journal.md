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

## Phase 2 · Feature 11 — Extraction schemas  *(2026-06-23)*

**Built:** `app/extraction/schemas.py` (`validate_request_schema`, `normalize_for_strict`,
`validate_output`, `InvalidSchemaError(ValueError)`, plus the private structure-aware
`_iter_subschemas` traversal); `app/models.py` (`ExtractRequest` only — `JobResponse`
deferred); `tests/test_extraction_schemas.py` (16 tests) + `tests/test_models.py` (6 tests).
No new dependencies (`jsonschema[format]` already in the stack); no SDK touched. Approved
plan: `~/.claude/plans/11-extraction-schemas-kind-naur.md`.

**Decisions** (architect session, developer-confirmed):
- **Submit-time gate = Pydantic `@field_validator`** on `ExtractRequest.output_schema`
  delegating to `validate_request_schema`. The gate raises `InvalidSchemaError`, a subclass
  of **`ValueError`** — Pydantic v2 catches a `ValueError` raised inside a validator and folds
  it into its own `ValidationError`, which FastAPI renders as **422** (F16). Both the JSON API
  and the dashboard-form path get the gate for free because both build `ExtractRequest`.
  Accepted cost: a one-way `app/models.py → app/extraction/schemas.py` import (no cycle —
  `schemas.py` imports nothing first-party).
- **Subset enforcement = targeted denylist** (not a full allowlist). Reject a fixed set of
  out-of-subset keywords (`oneOf`, `allOf`, `not`, `if`/`then`/`else`, `contains`,
  `prefixItems`, `patternProperties`, `dependentSchemas`, `dependentRequired`, `propertyNames`,
  `unevaluatedProperties`, `unevaluatedItems`) plus a hard root-`type:object` rule; tolerate
  anything else `check_schema` accepts (incl. numeric/length bounds — validation-only, not
  provider-guaranteed).
- **`JobResponse` deferred to F13/F16** — it needs `Job`/`JobStatus`, which land with the job
  store in F13. Deliberate deviation from the build-plan's "ExtractRequest + JobResponse"
  wording (annotated in `build-plan.md`), so `from_job()` and the status enum land together
  with no rework.
- **Validate output against the ORIGINAL schema, not the normalized one.** The user's schema
  is their contract; `normalize_for_strict` (all-required + `additionalProperties:false`) is
  only the provider's strict-tool input. A strict LLM output trivially satisfies the looser
  original, so validating against the original is both correct and what `architecture.md` /
  `library-docs.md` specify.
- **F11 lets the output `ValidationError` propagate unwrapped** — F12's engine wraps it into a
  `ProviderError` (`"extraction did not match schema: …"`). F11 owns the mechanism; the
  HTTP/job-error mapping is F12's/F16's.
- **`provider` field stays `str | None`** (matches the canonical `library-docs.md` model);
  unknown providers are handled by the registry's `ProviderError` (F10), not constrained here.

**Gotchas:**
- **Property names vs keywords (the denylist trap).** A naive "reject if any denylisted key
  appears anywhere" would wrongly reject `{"type":"object","properties":{"not":{...}}}` — there
  `not` is a *field name*, not the keyword. Fix: `_iter_subschemas` descends **only** through
  schema positions — single-subschema keys (`items`, `not`, `if`, …), list-of-subschema keys
  (`anyOf`/`allOf`/`oneOf`/`prefixItems`), and map-of-subschema keys (`properties`/`$defs`/
  `definitions`/`patternProperties`/`dependentSchemas`, whose **values** are subschemas and
  **keys** are names). Data-valued keywords (`enum`, `const`, `default`) are never traversed.
  Two tests pin this (a property named `not`/`if` accepted; `enum`/`const` strings not flagged).
- **`FORMAT_CHECKER` is required for `format`.** Plain `jsonschema.validate` ignores `format`;
  the test for a malformed `email` only fails because `validate_output` builds
  `Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)`. Confirmed
  `email` is an active checker in the installed `jsonschema[format]` (alongside `date-time`,
  `uri`, `uuid`, …).
- **Normalize must not mutate the request schema.** The original is kept (on the Job) for
  output validation, so `normalize_for_strict` `copy.deepcopy`s first; a test asserts the input
  is unchanged. Nodes are collected (`list(_iter_subschemas(clone))`) before mutating to avoid
  dict-changed-size-during-iteration.
- **ruff reformatted `tests/test_extraction_schemas.py`** (collapsed two wrapped dict literals) —
  applied `ruff format`, no logic change.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 40 files formatted.
- `uv run pytest -q` → **149 passed, 1 skipped** (127 prior + 22 new), exit 0. The skip is the
  Chromium-gated browser integration test (absent binary locally); one pre-existing
  Starlette/httpx TestClient deprecation warning, unrelated.
- Confirmed by test: a valid subset schema is accepted and validates good/bad payloads;
  root-non-object, root-missing-type, malformed (`check_schema`), and top-level + nested
  out-of-subset keywords are all rejected — both directly and through `ExtractRequest`
  (Pydantic `ValidationError`); a property named `not`/`if` and `enum`/`const` keyword-strings
  are accepted; `normalize_for_strict` fills nested object nodes under `properties`/`items`/
  `anyOf`/`$defs` without mutating the original and leaves leaf/propertyless nodes alone; a
  malformed `email` fails (`FORMAT_CHECKER` on); a `{"items": [...]}` envelope validates.
- Invariants held: `app/extraction/schemas.py` imports only stdlib + `jsonschema` — no
  `httpx`/`playwright`/SDK, no network/job-state, no `os`/env; no `create_model`; the only new
  import edge is `app/models.py → app/extraction/schemas.py` (no cycle).

---

## Phase 2 · Feature 12 — Extraction engine  *(2026-06-23)*

**Built:** `app/extraction/engine.py` (`async extract(content, *, prompt, schema,
provider) -> dict[str, Any]`); `tests/test_extraction_engine.py` (6 tests). No new
dependencies (`jsonschema` already in the stack); no SDK touched. Closes Phase 2.
Approved plan: `~/.claude/plans/12-extraction-engine-curried-island.md`.

**Decisions** (architect session, developer-confirmed):
- **Provider is injected, not selected by the engine** (developer's call between the two
  options presented). Signature is `extract(content, *, prompt, schema, provider:
  LLMProvider)`; the engine imports neither `registry` nor `Settings`. The **F14 runner**
  will build the provider via `registry.get_provider(settings, override=
  job.request.provider)` and pass it in. **Documented deviation** from `architecture.md`'s
  data-flow snippet (`provider = registry.get_provider(settings)` inside the engine) —
  annotated under F12 in `build-plan.md`, same as F11's `JobResponse` deferral note.
  Rationale: a registry-free engine is trivially testable with a fake provider (no
  monkeypatching), and keeps provider lifecycle/selection in one place (the runner).
- **Normalize before extract; validate against the original** (locked by F11). The
  provider receives `normalize_for_strict(schema)` as `json_schema`; the raw result is
  validated against the **un-normalized** `schema`. `schema is None` → `json_schema=None`
  and validation is skipped entirely.
- **Reuse F11's `validate_output`** (don't rebuild a `Draft202012Validator`) — it already
  enables `FORMAT_CHECKER` and deliberately raises the raw jsonschema `ValidationError`
  for the engine to wrap.
- **Schema mismatch → `ProviderError`** with the documented message `f"extraction did not
  match schema: {exc.message}"` (uses `exc.message`, not `str(exc)`, so it stays
  readable/user-safe). Per `library-docs.md`.
- **Engine's only `try/except` wraps the validation step, never the provider call.** A
  `ProviderError` from the provider (or the registry, upstream) propagates unchanged — the
  F14 runner is the top-level error boundary. The engine adds no untrusted-content framing
  (that is the provider's job, F10).

**Gotchas:**
- **Validating against the original is what makes the "extra key passes" test meaningful.**
  For `{"type":"object","properties":{"name":{"type":"string"}}}`, a result `{"name":"x",
  "extra":1}` passes (the original has no `additionalProperties:false`) — proving the
  validation target is the original, not the strict-normalized schema. A separate test
  asserts the provider *received* the normalized schema (`additionalProperties:false` +
  `required:["name"]`), pinning both halves.
- **`normalize_for_strict` deep-copies**, so a test asserts the caller's `schema` dict is
  byte-for-byte unchanged after `extract()` — the engine never mutates request state.
- **No `pytest.mark.asyncio` needed** — `asyncio_mode = "auto"` (set in F01). The fake
  provider records the `json_schema`/`content`/`prompt` it received for assertions, and
  can be primed to raise (provider-error passthrough test).

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 42 files
  formatted.
- `uv run pytest -q` → **155 passed, 1 skipped** (149 prior + 6 new), exit 0. The skip is
  the Chromium-gated browser integration test; one pre-existing Starlette/httpx TestClient
  deprecation warning, unrelated.
- Confirmed by test: happy path returns the result and the provider is handed the
  normalized schema; validation targets the original (extra-key result passes); a
  type-mismatch result → `ProviderError` starting `"extraction did not match schema:"`;
  `schema=None` skips validation and forwards `json_schema=None`, returning the dict
  verbatim; a provider `ProviderError` propagates unchanged (`is` the same object); the
  original schema is not mutated.
- Invariants held: `app/extraction/engine.py` imports only stdlib `typing`, `jsonschema`,
  and `app.extraction.schemas` / `app.providers.base` — no LLM SDK, no `httpx`/`playwright`,
  no network/job-state, no `os`/env, and **no registry** (provider arrives injected).

---

## Phase 3 · Feature 13 — In-memory job store  *(2026-06-23)*

**Built:** `app/jobs/models.py` (`Job` Pydantic model + `is_terminal`; `JobStatus(StrEnum)`);
`app/jobs/store.py` (`JobStore` + `JobStateError`); `JobResponse` added to `app/models.py`;
`tests/test_jobs_models.py` (3 tests) + `tests/test_jobs_store.py` (14 tests) + 2 new
`JobResponse.from_job` tests in `tests/test_models.py`. No new dependencies (stdlib `uuid`/
`datetime`/`asyncio` + Pydantic). Opens Phase 3. Approved plan:
`~/.claude/plans/13-in-memory-job-vivid-parrot.md`.

**Decisions** (architect session, developer-confirmed):
- **Transitions are enforced** (developer's call). `mark_running` requires `queued`;
  `mark_done`/`mark_error` require **non-terminal**; a missing id or a terminal-job mutation
  raises a new `JobStateError(RuntimeError)`. Protects the "terminal states never change"
  invariant. `mark_error` is allowed from `queued` *or* `running` (the F16 shutdown path marks
  a just-created `queued` job `error`).
- **`JobResponse` echoes the request** (developer's call): `job_id, status, url, prompt, mode,
  result, error, created_at, started_at, finished_at`, built by `from_job(job)`, so an API
  client polling `GET /jobs/{id}` sees which job without a second lookup. The dashboard (F18)
  reads full `Job`s from `list()` directly, so it doesn't depend on this echo.
- **Import-cycle break (the structural gotcha).** `app/jobs/models.py` imports `ExtractRequest`
  from `app/models` at runtime (real `Job.request` field), so `app/models.py` must **not**
  import from `app/jobs` at runtime — otherwise a circular import. Resolved by keeping
  `JobResponse` in its documented home (`app/models.py`) but importing `Job` **only under
  `TYPE_CHECKING`** (string annotation on `from_job`) and typing `JobResponse.status` as a plain
  **`str`** (fed `job.status.value`). Both import orders now resolve (verified). Trade-off: the
  response model's OpenAPI shows `status` as a string, not an enum — accepted (a `Literal` would
  duplicate the four values).
- **Lazy eviction, no background task.** `_evict()` runs under the lock at the top of `create()`
  and `list()` — a TTL sweep (terminal jobs whose `finished_at` is older than `JOB_TTL_SECONDS`)
  then an oldest-**terminal** sweep down to `MAX_JOBS`. `queued`/`running` are never touched. No
  fire-and-forget sweeper (respects the bounded-scheduler invariant). `MAX_JOBS` is therefore a
  **soft** cap: an all-non-terminal overflow is left over the cap (F15 admission bounds that).
- **Newest-first via `reversed(self._jobs.values())`**, not a `created_at` sort — dict insertion
  order == creation order, so rapid same-microsecond creations stay deterministic without
  depending on clock resolution.
- **Live references, not defensive copies.** `get`/`list`/`mark_*` return the stored `Job`
  objects (single-process, callers read-only); the runner reads `job.request` off
  `mark_running`'s return. All mutation goes through `mark_*` under the lock; `Job` is a mutable
  Pydantic model mutated in place.
- **Lifespan wiring deferred to F14** (the runner is the first `app.state.job_store` consumer) —
  `app/main.py` untouched, matching the F05/F06→F07 build-in-isolation precedent.
- **Test files** are `tests/test_jobs_models.py` / `tests/test_jobs_store.py` (test-per-module
  convention, e.g. `test_fetch_models.py`), not the architecture tree's coarse `test_jobs.py`.

**Gotchas:**
- **`JobStatus` had to be `StrEnum`, not `(str, Enum)`.** ruff `UP042` (in the selected `UP`
  ruleset) flags `class JobStatus(str, Enum)` and demands `enum.StrEnum`. The `library-docs.md`
  Pydantic snippet writes `(str, Enum)` illustratively, but ruff is the project's style authority
  (code-standards), so the real enum is `StrEnum`. `.value` is used explicitly everywhere, so the
  `str()` behaviour difference is moot; identity checks (`status is JobStatus.queued`) still hold.
- **TTL tested without sleeping.** Because `get`/`mark_*` return live refs and the store holds the
  same object, a test marks a job terminal then sets `job.finished_at` into the past and triggers
  a sweep via `list()` — deterministic, no `time.sleep`.
- **`MAX_JOBS` test must respect the settings relationship.** `Settings` enforces
  `max_concurrent_jobs <= max_queued_jobs <= max_jobs`, so the small-cap test sets
  `max_concurrent_jobs=1, max_queued_jobs=1, max_jobs=2` (not just `max_jobs=2`, which would fail
  construction). Eviction runs at the *top* of `create`, so the cap is enforced on the *next*
  `create()`/`list()` after the overflow insert — the test triggers it with a trailing `list()`.
- **Several docstrings/asserts tripped E501.** Shortened in place; no `noqa`.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 46 files formatted.
- `uv run pytest -q` → **174 passed, 1 skipped** (155 prior + 19 new), exit 0. The skip is the
  Chromium-gated browser integration test; one pre-existing Starlette/httpx TestClient deprecation
  warning, unrelated.
- Confirmed by test: `create()` → `queued` Job with a uuid4 id, tz-aware UTC `created_at`, null
  started/finished, request echoed; `get` round-trips and `get(unknown)→None`; `mark_*` set status
  + the right timestamp; illegal/terminal/missing transitions raise `JobStateError`; `mark_error`
  works from both `queued` and `running`; `list()` is newest-first; TTL drops only terminal jobs
  (running/queued survive an aged timestamp); `MAX_JOBS` drops oldest terminal but keeps
  non-terminal over the cap; `JobResponse.from_job` maps every field (`url` as str, `status` as a
  plain str value); 20 concurrent `create()`s all land distinct (lock holds).
- Invariants held (grep-verified): `app/jobs/` imports no `httpx`/`playwright`/LLM SDK and no
  `os`/env; `app/main.py` untouched; both import directions resolve (no runtime cycle); the only
  new cross-module edge is `app/jobs/models.py → app/models.py`.

---

## Phase 3 · Feature 14 — Async job runner  *(2026-06-23)*

**Built:** `app/jobs/runner.py` (`async run_job(job_id, *, app_state)`, the
`RunnerState` Protocol, and the best-effort `_terminalize` helper); lifespan wiring in
`app/main.py` (`app.state.job_store = JobStore(settings=settings)`, F13-deferred);
`tests/test_jobs_runner.py` (10 tests) + 1 new lifespan test in `tests/test_main.py`. No
new dependencies; no new exception types. Approved plan:
`~/.claude/plans/f14-async-job-vivid-harbor.md`.

**Decisions** (architect session, developer-confirmed):
- **`app_state` typed via a local `RunnerState` Protocol** (`job_store`, `browser_manager`,
  `settings`) rather than `Any`. Satisfies the full-type-hints rule, documents exactly what
  the runner reads off `app.state`, keeps the test's `SimpleNamespace` type-clean, and F15's
  scheduler can reuse the same shape. (Static checkers can't prove the dynamic Starlette
  `State` satisfies it, but it still documents + types the test double.)
- **Known-error tuple = `(ProviderError, FetchError, ValidationError)`** — matches the
  `code-standards.md` runner example and is forward-compatible. **Accepted deviation from
  reachability:** the jsonschema `ValidationError` arm is currently **unreachable** because
  the F12 engine already wraps schema-validation errors into `ProviderError`; including it
  pulls `jsonschema.exceptions` into `app/jobs`. Developer chose to match house style over
  trimming the dead branch.
- **Self-guarding terminalization upholds "never raises" unconditionally.** Both `except`
  arms route through one `_terminalize()` that swallows `JobStateError`, so the boundary
  holds even when the job is already terminal/evicted (an F15 shutdown race) or `mark_running`
  fails on a missing id. `JobStateError` is treated as internal/unknown (generic message +
  `logger.exception`).
- **Everything comes from `app_state`** (incl. `settings = app_state.settings`, already on
  `app.state` from F03). Module-qualified imports (`fetch_service.fetch`, `cleaner.clean`,
  `engine.extract`, `registry.get_provider`) give clean `monkeypatch.setattr` seams — the
  same style as `test_fetch_service.py`.
- **Provider built in the runner** via `registry.get_provider(settings,
  override=job.request.provider)` and injected into `engine.extract` — realizes the F12
  contract (engine selects no provider). The runner is the single place selection happens.
- **`str(job.request.url)` coercion** — `ExtractRequest.url` is `HttpUrl`; the fetch path /
  `url_guard` take `str` (`JobResponse.from_job` set the same precedent). A test pins that
  `fetch_service.fetch` receives a `str`.

**Gotchas:**
- **The guard must wrap BOTH `except` arms, not just the unknown one.** The known-error arm
  also calls `mark_error`, which can itself raise `JobStateError` (terminal/missing job) and
  escape — so a single `_terminalize()` helper serves both arms.
- **A plain `RuntimeError` is not a `ProviderError`/`FetchError`.** Both project errors
  subclass `RuntimeError`, but the reverse isn't true, so an arbitrary `RuntimeError` falls
  to `except Exception` → generic message. A test raises `RuntimeError("secret …")` and
  asserts the job error is exactly `"internal error — see server logs"` (no `str(exc)` leak).
- **`mark_running` on a terminal/missing job** raises `JobStateError` → `except Exception` →
  `_terminalize` → `mark_error` raises again → swallowed; the original terminal state is
  preserved (test pins a pre-`done` job stays `done` with its result).
- **Transitive SDK/browser imports are fine.** Importing `app.providers.registry` pulls in
  the `anthropic` SDK and `app.fetching.browser` pulls in `playwright`, but the runner imports
  **neither directly** — the invariant is about *direct* imports (same precedent as `main.py`
  importing `BrowserManager` and the engine importing `app.providers.base`).
- **TDD red steps observed:** the runner suite first failed with `ModuleNotFoundError`
  (no `app.jobs.runner`); the lifespan test first failed with `AttributeError: 'State' object
  has no attribute 'job_store'`. Both went green after implementation. ruff `E501` wrapped two
  test `store.create(...)` lines via `ruff format` (no logic change).

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 48 files formatted.
- `uv run pytest -q` → **185 passed, 1 skipped** (174 prior + 10 runner + 1 lifespan), exit 0.
  The skip is the Chromium-gated browser integration test; one pre-existing Starlette/httpx
  TestClient deprecation warning, unrelated.
- Confirmed by test: happy path → `done` with the result dict and `mode="http"`,
  `started_at`/`finished_at` set, `error` None; `mode="browser"` propagates; `FetchError`
  and its `SSRFError` subclass → `error` with the message verbatim; a registry `ProviderError`
  → `error`; a real schema mismatch through the engine → `error` starting `"extraction did not
  match schema:"`; an unknown `RuntimeError` → the generic message with no leak; `run_job`
  never raises against an already-terminal job (state preserved) or a missing id; the URL is
  passed as a `str` and the `provider` override is forwarded. Lifespan exposes
  `app.state.job_store` as a `JobStore`.
- Invariants held (grep-verified): `app/jobs/runner.py` imports no `httpx`/`playwright`/LLM
  SDK and no `os`/env *directly*; all state mutation goes through `JobStore` methods; the
  runner is the top-level error boundary and cannot raise.

---

## Phase 3 · Feature 15 — Job scheduler (concurrency, admission & shutdown)  *(2026-06-23)*

**Built:** `app/jobs/scheduler.py` (`Scheduler` + `SchedulerShuttingDown`); lifespan
wiring in `app/main.py` (`app.state.scheduler` + drain-before-browser-close);
`tests/test_jobs_scheduler.py` (9 tests) + 2 new lifespan tests in
`tests/test_main.py`. No new dependencies (stdlib `asyncio`/`logging` only); one new
exception type (`SchedulerShuttingDown`). Approved plan:
`~/.claude/plans/f15-job-scheduler-woolly-dragonfly.md`.

**Decisions** (architect session, developer-confirmed):
- **Two bounds, both required.** A `MAX_CONCURRENT_JOBS` `asyncio.Semaphore` caps the
  *running* subset; a synchronous, atomic `try_reserve()` (plain `int` `_reserved`,
  check-and-increment with **no `await` between**) caps *in-flight + waiting* at
  `MAX_QUEUED_JOBS`. A semaphore alone is unbounded — waiting tasks and their `queued`
  jobs accumulate. `try_reserve()` returns False when `_draining` or at cap.
- **`submit()` is synchronous** (the F16 handler calls it without `await`): it
  `asyncio.create_task(self._run(job_id))` and **retains a strong ref** in
  `self._tasks` (+ `add_done_callback(self._tasks.discard)`) — never a fire-and-forget
  `create_task`. Excess submissions block on the semaphore inside `_run` while still
  counting against the admission cap. `submit()` raises `SchedulerShuttingDown` only
  while draining.
- **Slot released in the task's `finally`, not on the store's terminal transition**
  (developer-confirmed). `_run` = `try: async with sem: await runner.run_job(...)
  finally: self.release()`. This releases exactly once per task **even under
  cancellation**, where `run_job` raises `CancelledError` and never reaches a terminal
  store transition. Normal flow: one reserve → one release. The F16 handler releases
  only on the no-task paths (failed `create`, `SchedulerShuttingDown` from `submit`).
- **Shutdown = grace, then cancel, then sweep** (confirmed via `AskUserQuestion`).
  `_draining = True` → `asyncio.wait(set(self._tasks), timeout=shutdown_grace_seconds)`
  → `cancel()` each still-pending task → `gather(*pending, return_exceptions=True)` to
  settle → `_terminalize_survivors()`. Runs **before** `browser_manager.aclose()` in
  the lifespan so a live render can't outlast Chromium.
- **Survivors terminalized by sweeping `store.list()`** (confirmed). Iterate
  `app_state.job_store.list()` and `mark_error(..., "server shutting down")` every
  non-terminal job, swallowing `JobStateError` on races (same best-effort shape as
  `runner._terminalize`). Catches both `queued`-on-semaphore tasks and `running` jobs
  whose tasks were cancelled (cancelled `run_job` never self-terminalizes — its
  `except Exception` doesn't catch `CancelledError`; the sweep is their terminalizer).
- **Reuses F14's `RunnerState` Protocol** as the `app_state` type (passed straight to
  `run_job`; `app_state.job_store` used for the sweep). Constructor matches
  `architecture.md`: `Scheduler(*, app_state, settings)`.
- **Test seam = monkeypatch `scheduler.runner.run_job`** (module-qualified call), the
  established project seam style (`fetch_service` → `http_fetcher.fetch`); no
  production-only injection param. F16's reserve→create→release/mark_error
  orchestration is **F16's** — F15 ships and unit-tests the primitives.

**Gotchas:**
- **Cancellation, not a flag, interrupts in-flight work.** `run_job` doesn't poll a
  draining flag mid-pipeline (it `await`s a long fetch/render), so the grace path must
  `task.cancel()` stragglers; the post-cancel store sweep is what records their error.
- **`asyncio.wait` gets a snapshot** (`set(self._tasks)`) because the `done_callback`
  mutates `self._tasks` as tasks finish during the wait.
- **`release()` keeps a defensive underflow guard** (`if self._reserved > 0`). The
  design never double-releases (handler releases only when no task was created), but
  the guard keeps shutdown robust.
- **Deterministic concurrency/shutdown tests, no wall-clock sleeps.** Jobs are gated
  on a never-set `asyncio.Event`; `shutdown_grace_seconds=0` forces the straggler/
  cancel path; peak-concurrency is observed by yielding `await asyncio.sleep(0)` ~20×
  to let everything that *can* run, run, then asserting peak == `MAX_CONCURRENT_JOBS`.
- **`max_*` test overrides must satisfy the settings relationship**
  (`max_concurrent_jobs <= max_queued_jobs <= max_jobs`), or `Settings` raises at
  construction (same constraint hit in the F13 store tests).
- **TDD red observed:** both new test modules first failed with
  `ModuleNotFoundError: No module named 'app.jobs.scheduler'`; green after
  implementation. ruff `format` reflowed one test file (no logic change).

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 50 files
  formatted.
- `uv run pytest -q` → **196 passed, 1 skipped** (185 prior + 9 scheduler + 2 lifespan),
  exit 0. The skip is the Chromium-gated browser integration test; one pre-existing
  Starlette/httpx TestClient deprecation warning, unrelated.
- Confirmed by test: `try_reserve()` admits exactly `max_queued_jobs` then rejects (no
  overshoot); `release()` frees a slot and underflow is a safe no-op; draining →
  `try_reserve()` False + `submit()` raises `SchedulerShuttingDown`; a submitted job
  runs `run_job` and releases its slot (task ref dropped after); concurrency never
  exceeds `MAX_CONCURRENT_JOBS` across hand-offs; shutdown leaves an in-grace job
  `done`, cancels an over-grace `running` job → `error` ("server shutting down"), and
  sweeps a `queued`-on-semaphore survivor → `error`; shutdown with no tasks is safe and
  idempotent. Lifespan: `app.state.scheduler` is a `Scheduler`, and `shutdown()` is
  awaited **before** `browser_manager.aclose()` (spy-recorded order).
- Invariants held (grep-verified): `app/jobs/scheduler.py` imports no
  `httpx`/`playwright`/LLM SDK and no `os`/env; all job-state mutation goes through
  `JobStore` methods; every task is retained (no fire-and-forget `create_task`); drain
  precedes browser close.

---

## Phase 3 · Feature 16 — Extract & jobs API endpoints  *(2026-06-23)*

**Built:** `app/api/extract.py` (`router` with `POST /extract`, `GET /jobs`,
`GET /jobs/{job_id}`); `app/api/security.py` (`require_trusted_origin` dependency);
router wired into `create_app()` in `app/main.py`; `tests/test_api_extract.py` (10
tests). No new dependencies (FastAPI/Starlette already in the stack); no new exception
types. **Closes Phase 3.** Approved plan: `~/.claude/plans/f16-extract-abundant-stearns.md`.

**Decisions** (architect session, developer-confirmed):
- **Origin check = lenient + shared dependency.** `require_trusted_origin` lives in a new
  `app/api/security.py` (not inline) because F17's dashboard POST reuses it (a second
  consumer is certain per the build-plan). **Lenient policy** (chosen over strict): a
  *missing* `Origin` is allowed so the documented non-browser clients (curl/httpx/
  server-to-server) keep working; a *present* `Origin` whose host ∉ `ALLOWED_HOSTS` →
  `403`. Wired as a route `dependencies=[Depends(require_trusted_origin)]` on
  `POST /extract` only (GETs are not state-changing).
- **At capacity → `429 + Retry-After`** (chosen over `503`; architecture lists both).
  `_RETRY_AFTER_SECONDS = 5` module constant. The **distinct** shutdown-race path
  (`submit()` → `SchedulerShuttingDown`) stays **`503` "server shutting down"** — a
  "going away" signal, matching the canonical `code-standards.md` snippet. So: backpressure
  = 429, draining = 503.
- **Handler owns the exact canonical orchestration** from `architecture.md` /
  `code-standards.md`: `try_reserve()` (atomic, before `create`) → `try: await
  store.create(req) except BaseException: release(); raise` → `try: scheduler.submit(job.id)
  except SchedulerShuttingDown: release(); await store.mark_error(..., "server shutting
  down"); raise 503 from None`. No new flow invented.
- **Status codes as integer literals** (`202`/`429`/`503`/`404`/`403`) + `Retry-After`
  via `HTTPException(headers=...)` — matches `health.py` house style; no `from fastapi
  import status`.
- **Origin dependency reads `request.app.state.settings`** (lifespan-set, == cached
  `get_settings()`), consistent with how the handlers read `app.state.scheduler` /
  `.job_store`. `urlsplit(origin).hostname` vs plain membership in `allowed_hosts`
  (wildcard `ALLOWED_HOSTS` entries aren't expanded — a v1 simplification; default is
  `127.0.0.1,localhost`).
- **One test file** `tests/test_api_extract.py` exercises the Origin guard *through* the
  route (its only real consumer) rather than a separate `test_api_security.py` — same
  test-per-module convention, no unit test for a 6-line guard.
- **`provider` not constrained at the boundary** (locked F10/F11): an unknown provider
  string isn't a 422; it becomes a runtime job `error` via the registry's `ProviderError`.

**Gotchas:**
- **`B904` on the 503 re-raise.** Ruff's `B` ruleset flags `raise HTTPException(...)`
  inside the `except SchedulerShuttingDown` block; `SchedulerShuttingDown` is *expected
  control flow*, not an error to chain, so `raise ... from None` is the correct fix (the
  canonical code-standards snippet omits it, but it's illustrative — ruff is the style
  authority).
- **Per-test store isolation comes free from the lifespan.** `app` is the module-level
  singleton, but each `with TestClient(app)` re-runs startup, which reassigns
  `app.state.job_store`/`.scheduler` — so a fresh store per test without a fixture. Tests
  that assert "no job created" (`429`, `403`) rely on this (`GET /jobs == []`).
- **Background-task polling under the sync TestClient.** `scheduler.submit` schedules an
  `asyncio.create_task`; after the `202` returns, the task runs on the TestClient portal's
  loop. A bounded `_poll_until_terminal` loop on `GET /jobs/{id}` pumps that loop and
  observes the stubbed runner reach `done` (converges in 1–2 GETs). No `sleep`.
- **Stub the runner to stay offline.** Any successful-submit test monkeypatches
  `app.jobs.runner.run_job` (the established F15 seam, called module-qualified in
  `scheduler._run`) with a fake that `mark_running` → `mark_done` — otherwise the real
  pipeline would hit `example.com`. The `422`/`403`/`429` tests need no stub (no job runs).
- **Forcing the capacity branch deterministically** = `monkeypatch.setattr(app.state.
  scheduler, "try_reserve", lambda: False)` after entering the client, so the test doesn't
  depend on the configured `MAX_QUEUED_JOBS`. The shutdown-race test monkeypatches
  `scheduler.submit` to raise `SchedulerShuttingDown` and asserts the job is `error` and
  `scheduler._reserved == 0` (slot released).
- **Two `E501` overflows** (long inline comments / a one-line dict-spread `post`) — fixed
  by reflowing the comment and hoisting the payload to a local; no `noqa`.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 53 files
  formatted.
- `uv run pytest -q` → **206 passed, 1 skipped** (196 prior + 10 new), exit 0. The skip is
  the Chromium-gated browser integration test; one pre-existing Starlette/httpx TestClient
  deprecation warning, unrelated.
- Confirmed by test: submit → `202` + `JobResponse(status="queued")` and polls to `done`
  with the stubbed result/`mode`; `GET /jobs` newest-first; unknown id → `404`;
  root-non-object `output_schema` → `422` and a valid subset schema → `202`; at capacity →
  `429` + `Retry-After: 5` with **no job created**; shutdown race → `503` with the job
  terminalized `error` ("server shutting down") and the reserved slot released; a
  disallowed Origin → `403` (no job), an allowed/missing Origin → `202`.
- Invariants held: handler carries no scraping/cleaning/LLM logic (validate → reserve →
  call the job service → shape `JobResponse`); admission reserved atomically before
  `create()` and released on every failure path; `SchedulerShuttingDown` caught
  specifically (never broad `BaseException`); `app/api/` imports no `httpx`/`playwright`/
  LLM SDK and no `os`/env.

---

## Phase 4 · Feature 17 — Dashboard layout & submission form  *(2026-06-23)*

**Built:** `app/jobs/submission.py` (`enqueue` + `AtCapacityError`); `app/dashboard/routes.py`
(`GET /`, `POST /submit`); `templates/{base,index}.html` + `_jobs_container.html` +
`_submit_result.html`; `static/styles.css`; vendored `static/htmx.min.js` (htmx 2.0.4);
`app/api/extract.py` refactored onto `enqueue`; `app/main.py` mounts `/static` +
`app.state.templates` + the dashboard router; `tests/test_dashboard.py` (10) +
`tests/test_jobs_submission.py` (4). New dependency `python-multipart` (added to the approved
list in `code-standards.md`, `pyproject.toml`, `uv.lock`). Opens Phase 4. Approved plan:
`~/.claude/plans/feature-17-dashboard-quirky-stearns.md`.

**Decisions** (architect session, developer-confirmed via AskUserQuestion):
- **Shared `enqueue` helper, not duplicated admission code** (developer's call). The atomic
  `try_reserve()` → `create()` → `submit()` sequence — safety-critical and previously inline in
  the F16 handler — now lives once in `app/jobs/submission.py::enqueue(request, *, scheduler,
  store) -> Job`, raising `AtCapacityError` (gate closed) or re-raising `SchedulerShuttingDown`
  (after `release()` + `mark_error`). Each caller maps to its medium: `/extract` →
  `429`+`Retry-After` / `503`; dashboard → inline error fragment. The F16 handler shed ~20 lines
  and its `logging` import; behaviour is unchanged (its tests still pass untouched).
- **HTMX form + OOB re-arm, not PRG** (developer's call). The form `hx-post`s to `/submit`,
  `hx-target="#submit-result"`. Success returns `_submit_result.html` = a "Job queued" note **plus
  an `hx-swap-oob="true"` re-render of `#jobs`** (same id → out-of-band swap) carrying
  `hx-trigger="load, every 2s"`; its `load` fires immediately, re-arming a poller stopped by F18's
  `286`. Because the fragment targets `#submit-result` (not the form), typed values persist with no
  echoing.
- **Inline error returns HTTP `200`, not `400`** (senior-engineer catch, flagged at plan time).
  HTMX does **not** swap non-2xx responses by default, so a `400` error fragment would never render.
  The route catches `(json.JSONDecodeError, ValidationError)` *before* `enqueue` and
  `AtCapacityError`/`SchedulerShuttingDown` after, rendering an `ok=False` fragment at `200`. No job
  is created on any error path (asserted via `GET /jobs == []`).
- **`Form(...)`-decoded, not JSON** (option 1 from `library-docs.md`). `output_schema` arrives as a
  textarea **string** → `json.loads` (blank → `None`) before building `ExtractRequest`, whose F11
  `@field_validator` still gates the subset. Reuses `require_trusted_origin` (F16) as a route dep.
- **htmx vendored same-origin, not CDN** (prompted by the security hook's SRI warning). Downloaded
  htmx 2.0.4 to `static/htmx.min.js` and served it from `/static`, eliminating the CDN-compromise /
  Subresource-Integrity concern entirely (and it works offline — fitting a localhost tool). Its
  sha384 matched the published htmx 2.0.4 integrity hash, confirming authenticity.

**Gotchas:**
- **`python-multipart` was missing.** FastAPI's `Form(...)` (and Starlette's urlencoded parsing)
  require it, but it wasn't in the stack — `import multipart` failed. The documented `Form(...)`
  design assumed it. Added it per the "update the approved-deps list first" rule, then `uv add`.
- **`JobResponse` has no `render` field**, so the plan's "verify `render` via `GET /jobs`" was wrong.
  Verified the render checkbox mapping instead by spying on `enqueue` (monkeypatch
  `app.dashboard.routes.enqueue` with a wrapper that captures the built `ExtractRequest`): box
  absent → `render is False`; `value="true"` checked → `render is True` (Pydantic v2 bool-coerces
  `"true"`).
- **`StaticFiles(directory="static")` is constructed at `create_app()` import time** — the dir must
  exist or it raises immediately. The first `curl -o static/...` failed (exit 56) because `static/`
  didn't exist yet; `mkdir -p static` first fixed it. `static/styles.css` keeps the dir present.
- **OOB include flag.** `_jobs_container.html` takes an `oob` var; `index.html` includes it without
  setting `oob` (Jinja `Undefined` → falsy → no `hx-swap-oob`), while `_submit_result.html` does
  `{% set oob = True %}` before the include. One template, both uses.
- **ruff** reordered the `app/jobs/submission.py` imports and reformatted `tests/test_dashboard.py`;
  one docstring `E501` was reworded by hand (auto-fix won't touch docstrings).

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 57 files formatted.
- `uv run pytest -q` → **220 passed, 1 skipped** (206 prior + 10 dashboard + 4 submission), exit 0.
  The skip is the Chromium-gated browser integration test; one pre-existing Starlette/httpx
  TestClient deprecation warning, unrelated.
- Confirmed by test: `GET /` → `200` HTML with the form, the unchecked `render` checkbox + risk note,
  `#submit-result`, and the `#jobs` container with `every 2s`; a valid submit creates the job and the
  response re-arms polling (`hx-swap-oob` + `every 2s`); render maps false/true; a valid subset schema
  is accepted; malformed-JSON, out-of-subset, and invalid-URL inputs each return an inline `200` error
  and create **no** job; a disallowed `Origin` → `403`; at capacity → inline "capacity" message, no
  job. `enqueue` unit tests: returns/creates/submits on the happy path; `AtCapacityError` when reserve
  fails (no job); slot released when `create()` raises; slot released **and** job terminalized `error`
  when `submit()` raises `SchedulerShuttingDown`.
- Manual smoke (TestClient): `/static/htmx.min.js` serves `200` (50,917 bytes), and `GET /` references
  the vendored script.
- Invariants held (grep-verified): `app/dashboard/` imports no `httpx`/`playwright`/LLM SDK and no
  `os`/env; templates carry **no** `| safe` (Jinja2 autoescaping intact); the dashboard POST calls the
  shared `enqueue` (no second copy of admission logic).

---

## Phase 4 · Feature 18 — Jobs list & live status  *(2026-06-23)*

**Built:** `templates/_jobs_table.html` (the live jobs table — innerHTML of the F17
`#jobs` container); `GET /partials/jobs` added to `app/dashboard/routes.py` (+ a
`_STOP_POLLING_STATUS = 286` constant); table/status CSS appended to
`static/styles.css`; 5 new tests in `tests/test_dashboard.py`. No new dependencies; no
new exception types; container/submit wiring from F17 untouched. Approved plan:
`~/.claude/plans/feature-18-jobs-happy-papert.md`.

**Decisions** (architect session, developer-confirmed):
- **`286` stops polling AND swaps the body — verified, not assumed.** Context7
  `/bigskysoftware/htmx`: htmx's default `responseHandling` is
  `{"code":"[23]..","swap":true}`, so `286` (matches `[23]..`) is swapped *and* the
  polling docs confirm `286` halts the poll. So the final poll updates the table to its
  terminal rows *before* stopping — no one-tick-stale bug. The team's documented `286`
  choice holds.
- **Stop condition = `all(job.is_terminal for job in jobs)`.** `all([])` is `True`, so
  the **empty** table returns `286` too (one expression covers both "empty" and "all
  terminal"); any `queued`/`running` job → `200` and polling continues.
- **Plain full-UUID id now; the `/jobs/{id}/view` link is deferred to F19** (scope — no
  link that 404s until the route exists).
- **All three timestamps, UTC `HH:MM:SS`** via `strftime`, `—` when `None`; date omitted
  (jobs are short-lived/in-memory). Formatting is inline in the template (the datetimes
  are tz-aware UTC, so `strftime` is already UTC) — no Jinja filter added.
- **Status as `<span class="status status-{{ job.status }}">`** (StrEnum renders its
  value) so CSS styles each state; reused the existing `--ok-*`/`--err-*`/`--accent`/
  `--muted` vars (done/error/running/queued).
- **No untrusted fields in this table → no escaping test here.** Rows render only a UUID,
  the status enum, `"http"`/`"browser"` mode, and timestamps; result/error text (the
  untrusted content) is F19's detail page. Jinja autoescaping stays globally on.
- **Empty-state message lives in `_jobs_table.html`** (`No jobs yet — submit one
  above.`), matching the placeholder F17 seeded in the container — the `load` poll
  immediately replaces the container's innerHTML with this partial.

**Gotchas:**
- **Deterministic tests without the scheduler:** monkeypatch `app.state.job_store.list`
  to return crafted `Job`s (no event-loop race on background tasks). Safe at lifespan
  shutdown even for **non-terminal** crafted jobs because `Scheduler._terminalize_survivors`
  calls `mark_error` on ids absent from the *real* store, which raises a **swallowed**
  `JobStateError` (confirmed by reading `scheduler.py`). One integration test instead
  stubs `runner.run_job` to a no-op so a real submitted job stays `queued` (it is
  `await store.create`-d inside the POST handler, so it exists regardless of whether the
  background task ran) → `/partials/jobs` deterministically returns `200`.
- **TestClient does not raise on `286`** (httpx only raises via `raise_for_status`), so
  the `286` assertions read `resp.status_code` directly.
- **`TemplateResponse` carries the status code** — passed as `status_code=` (4th positional
  is `status_code` via keyword) so the partial renders with `286`/`200` as computed.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 57 files
  formatted (clean).
- `uv run pytest -q` → **225 passed, 1 skipped** (220 prior + 5 new), exit 0. The skip is
  the Chromium-gated browser integration test; one pre-existing Starlette/httpx TestClient
  deprecation warning, unrelated.
- Confirmed by test: empty store → `286` + "No jobs yet"; all-terminal (`done`+`error`) →
  `286` with both rows rendered; a `queued`/`done` mix → `200` with `status-queued`; a
  `running` row shows id, `running`, `browser`, the `14:02:11` UTC time, and `—` for the
  unset `finished_at`; an end-to-end submit (no-op runner) leaves a `queued` row and
  `/partials/jobs` → `200`.
- Invariants held: `app/dashboard/routes.py` only reads the store (no scraping/cleaning/LLM
  logic); no `| safe` in templates (autoescaping intact); no new dependency; no `os`/env
  access; the F17 `#jobs` container and submit re-arm are unchanged.

---

## Phase 4 · Feature 19 — Job detail & result viewer  *(2026-06-23)*

**Built:** `templates/job_detail.html` (new full page, `extends base.html` — the single-job
detail view); `GET /jobs/{job_id}/view` added to `app/dashboard/routes.py`; the job-id cell in
`templates/_jobs_table.html` turned into `<a href="/jobs/{id}/view">`; detail CSS appended to
`static/styles.css` (`.back`, `.detail-meta`, `pre.result-json`); 7 new tests in
`tests/test_dashboard.py`. No new dependencies; no new exception types. Approved plan:
`~/.claude/plans/f19-job-detail-calm-hellman.md`.

**Decisions** (architect session, developer-confirmed):
- **Unknown/evicted id → styled HTML 404, not JSON.** The detail route returns the
  `job_detail.html` template with `job=None` and `status_code=404`, which renders a small
  "Job not found" state + a back link. One template owns both the found and not-found states
  (keeps the thin dashboard's file count low). This deliberately diverges from the API's
  `GET /jobs/{id}` (which raises a JSON `HTTPException(404)`) because this route is browser-facing.
- **Static snapshot, no polling.** The page renders the job's state once at load; a
  `queued`/`running` job shows a "still in progress — refresh, or watch the dashboard table" note.
  No HTMX polling here — in scope per build-plan F19, which only specifies rendering result/error.
- **Pretty-print in the handler, render in an autoescaped `<pre>`.**
  `result_json = json.dumps(job.result, indent=2, ensure_ascii=False)` is computed in the route
  (the `json` import already existed in `routes.py`) and rendered as `{{ result_json }}` inside
  `<pre class="result-json">`. This is the **first feature to render untrusted scraped content**
  (LLM output over page content), so the security crux is Jinja autoescaping with **no `| safe`** —
  an embedded `<script>` becomes inert `&lt;script&gt;` text. No `tojson` needed.
- **Surfaced request metadata too** (url, prompt, provider→"default" when unset, render→yes/no) plus
  status/mode/timestamps (`%Y-%m-%d %H:%M:%S UTC`, `—` when unset) via a `<dl class="detail-meta">`,
  so the page is a real "detail" view rather than just a JSON dump.
- **No Origin/CSRF dependency** — a read-only `GET`, unlike the state-changing `POST /submit`.

**Gotchas:**
- **Jinja autoescapes double quotes too** (`"` → `&#34;`, also `'` → `&#39;`), so the rendered
  `result_json` shows escaped quotes in the **raw HTML** (a browser displays them as normal quotes).
  The done-job test therefore asserts on word fragments (`"title"`, `"Hello"`) and the presence of the
  `result-json` block, not literal JSON punctuation. The XSS test asserts the *escaped* form
  `&lt;script&gt;alert(1)&lt;/script&gt;` is present and the raw `<script>alert(1)</script>` is absent.
- **`base.html` emits a literal `<script src="/static/htmx.min.js">` tag**, so a naive
  `"<script" not in body` assertion would false-positive. The XSS assertions use the full
  `<script>alert(1)</script>` payload string, which is specific enough to avoid the htmx tag.
- **`StrEnum` compares equal to its value**, so `{% if job.status == "done" %}` works directly in the
  template (no `.value` needed); `status-{{ job.status }}` also renders the bare value for the CSS class.
- **No route collision:** `GET /jobs/{job_id}/view` (3 segments) does not match the API's
  `GET /jobs/{job_id}` (2 segments) — Starlette path params don't span `/`.
- **ruff E501** on one test call (`_detail_job(...)` one-liner at 91 chars); `ruff format` rewrapped it.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 57 files formatted (clean).
- `uv run pytest -q` → **232 passed, 1 skipped** (225 prior + 7 new), exit 0. The skip is the
  Chromium-gated browser integration test; one pre-existing Starlette/httpx TestClient deprecation
  warning, unrelated.
- Confirmed by test: a `done` job renders its result in the `<pre>` (200); an `error` job renders its
  message (200); a `result`/`error` carrying `<script>`/`<img onerror>` is **escaped** (raw markup
  absent, `&lt;…` present) — no HTML injection; an unknown id → **404** with `text/html` and the
  "Job not found" state (not JSON); a `running` job → 200 with the in-progress note and **no**
  result/error block; the partial jobs table now contains `href="/jobs/{id}/view"`.
- Invariants held (grep-verified): `app/dashboard/routes.py` imports no `httpx`/`playwright`/LLM SDK and
  no `os`/env; no `| safe` in any template (only a comment in `job_detail.html` *naming* the rule);
  no new dependency.

---

## Phase 4 · Feature 20 — Result export  *(2026-06-23)*

**Built:** `app/dashboard/export.py` (new, pure: `result_to_json`, `result_to_csv`, plus private
`_rows_for` / `_columns_for` / `_render_cell` / `_escape_formula`); `GET /jobs/{job_id}/export` added
to `app/dashboard/routes.py`; export buttons in the **done** block of `templates/job_detail.html`;
`.exports`/`.export-btn` CSS in `static/styles.css`; `tests/test_export.py` (11 pure-module tests) +
8 route tests appended to `tests/test_dashboard.py`. No new dependencies (stdlib `csv`/`io`/`json`).
Closes Phase 4. Approved plan: `~/.claude/plans/f20-result-export-elegant-muffin.md`.

**Decisions** (architect session, developer-confirmed):
- **Serialization is a pure module, separate from the route** (`app/dashboard/export.py`). Keeps the
  handler thin (`code-standards.md` → no business logic in handlers) and makes the CSV matrix
  unit-testable without HTTP. Imports stdlib only — no FastAPI, no job state, no I/O.
- **CSV row detection = single-key list-of-objects envelope.** `_rows_for` returns the inner list
  **iff** the result has exactly one key whose value is a `list` of `dict`s (`all(isinstance(i, dict)…)`,
  which is vacuously true for an empty list → header-only). Every other shape — multi-key dict, single
  key with a scalar value, or a single key holding a **list of scalars** — becomes one row
  (`[result] if result else []`). The permissive "first list value anywhere" option was rejected: it
  silently drops sibling scalar fields.
- **Columns = union of row keys, first-seen order**, built with an insertion-ordered `dict` as a set
  (`setdefault`). Missing keys in a heterogeneous row → blank cell via `row.get(col)`.
- **Cell rendering:** `None` → `""`; `dict`/`list` → `json.dumps(…, ensure_ascii=False)` (nested values
  are JSON cells); everything else → `str(value)`. Formula-injection: a cell whose text starts with
  `= + - @` is prefixed with `'` — applied to **header and data** cells (keys are LLM/scrape-derived
  too). Per the spec's explicit rule, a negative number like `-5` is escaped to `'-5` (accepted
  tradeoff). `csv.writer` over `io.StringIO` handles comma/quote/newline quoting on top.
- **Plain `Response`, not `StreamingResponse`** — the result is a fully materialized in-memory dict, so
  streaming would be theater. Documented deviation from the build-plan's literal "streaming a file
  response" wording (the "no persistence" intent — generate on the fly, nothing written to disk — is
  honored). Returns `Content-Disposition: attachment; filename="job-{id}.{ext}"` with
  `application/json; charset=utf-8` / `text/csv; charset=utf-8`.
- **Status codes:** read-only `GET`, so **no Origin check** (matches `/jobs/{id}/view`). Unknown/evicted
  id → `HTTPException(404)`; a job that exists but has `result is None` (queued/running/error) →
  `HTTPException(409)`; `format` is a `Literal["json","csv"]` defaulting to `json`, so a bad value
  (`?format=xml`) → **422** at the boundary before the handler runs. Errors are `HTTPException` (JSON
  detail), not the styled-HTML 404 the `/view` *page* uses — export is a download trigger, not a page.

**Gotchas:**
- **`all(isinstance(i, dict) for i in [])` is `True`**, which is exactly what makes
  `{"items": []}` resolve to zero rows (header-only) rather than one row holding `"[]"`. A list of
  *scalars* (`{"tags": ["x","y"]}`) is non-empty and not all-dicts, so it correctly falls through to the
  one-row branch with the list JSON-encoded in its cell — pinned by a test.
- **Four `E501`s on docstrings/comments** in `export.py` on the first lint pass (the `= + - @`/`first-seen`
  phrasing ran long). Shortened the prose rather than adding `# noqa` (consistent with the codebase,
  which keeps lines ≤88 without suppressions). The `writer.writerow([...])` comprehension was wrapped.
- **`format` shadows the builtin** but ruff's selected rules (`E,F,I,UP,B`) don't include flake8-builtins
  (`A`), so it's clean; kept the name to bind the `?format=` query param.
- **CSV tests parse output back with `csv.reader`** and assert on **values, not quoting** — robust to
  how the writer quotes embedded commas/quotes/newlines (e.g. a JSON cell `["x", "y"]` is emitted quoted
  but reads back as the original string). Empty/empty-list cases assert `rows in ([], [[]])`.

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 59 files formatted.
- `uv run pytest -q` → **251 passed, 1 skipped** (232 prior + 19 new), exit 0. The skip is the
  Chromium-gated browser integration test; one pre-existing Starlette/httpx TestClient deprecation
  warning, unrelated.
- Confirmed by test: JSON export parses equal to the stored `result` with an `attachment`
  `Content-Disposition`; `?format` defaults to json; CSV of `{"items":[{"a":1},{"a":2,"b":3}]}` →
  header `a,b`, rows `1,` / `2,3`; single object → one row; list-of-scalars → one row with a JSON cell;
  nested dict/list → JSON cells; `{}` and `{"items":[]}` → header-only (no crash); each of `= + - @`
  neutralized with a `'` prefix; comma/quote/newline round-trip; unknown id → 404; running job → 409;
  `?format=xml` → 422; the done detail page shows both export links, a running one shows none.
- Invariants held: `app/dashboard/export.py` imports only stdlib (`csv`/`io`/`json`/`typing`) — no
  FastAPI, no job state, no network, no `os`/env; the route stays thin (lookup → serialize → Response);
  F19's result/error autoescaping is untouched.

---

## Phase 5 · Feature 21 — Error handling, timeouts, retries & respectful client  *(2026-06-23)*

**Built:** `app/fetching/respect.py` (new, `RespectfulClient`: per-host rolling-window rate
limiter + TTL robots.txt cache + `guard`/`check_rate_limit`/`check_robots`); two new error
types in `app/fetching/errors.py` (`RobotsDisallowedError`, `RateLimitedError`); render-timeout
mapping + `app.fetching` logger in `app/fetching/browser.py`; lifespan wiring in `app/main.py`
(`app.state.respectful_client`); `app/jobs/runner.py` (`RunnerState.respectful_client` +
`await guard(url)` before fetch); `tests/test_respect.py` (13) + 1 render-timeout test in
`tests/test_browser.py` + 2 gate-rejection tests in `tests/test_jobs_runner.py` + 1 lifespan
test in `tests/test_main.py`. **No new dependencies** (stdlib `urllib.robotparser`/`collections`/
`time`); **no new env vars**. Opens Phase 5. Approved plan:
`~/.claude/plans/21-error-handling-timeouts-wobbly-pie.md`.

**Decisions** (architect session, developer-confirmed via AskUserQuestion):
- **Most of "timeouts & retries" was already shipped** — fetch timeout + `TransientFetchError`
  (F05), render `goto` timeout in ms (F06), LLM `AsyncAnthropic(timeout=…)` (F10), bounded
  transient fetch retry (F07), readable job errors (F14). F21 **verified** these and built only
  the genuinely-new work: the respectful client, the deferred render-timeout map, and
  `app.fetching` logging. Did **not** re-implement timeouts/retries (confirmed scope).
- **Gate invoked by the runner, not inside `fetch_service`** (placement refinement). The
  `RespectfulClient` module lives in `app/fetching/`, but the call site is the runner
  (`await app_state.respectful_client.guard(url)` right after `mark_running`, before
  `fetch_service.fetch`). The runner is the sole caller of the fetch path, so it is the same
  single chokepoint covering both HTTP and render — and `fetch_service.fetch`'s signature and
  its 23 tests stay untouched. **Documented deviation** from the build-plan's "lives in
  app/fetching/ … before each fetch" wording (the *module* lives there; only the *call site* is
  the runner). Annotated under F21 in `build-plan.md`.
- **Rate-limit over the cap → reject** (confirmed). `check_rate_limit` raises a **non-retryable**
  `RateLimitedError(FetchError)`; the runner records it as a readable job `error`. Never holds a
  scheduler slot sleeping. Rolling-window: a `deque[float]` per host, prune `< now-60`, compare,
  append — **all synchronous, no `await` between** → atomic on the loop (same pattern as
  `scheduler.try_reserve`). `clock` is constructor-injectable for deterministic window tests.
- **robots fetch failure → fail-open / allow** (confirmed). Missing/4xx/5xx/timeout/unreachable
  → allow (logged). **Exception:** an `SSRFError` from the robots fetch **propagates** (caught
  specifically and re-raised before the broad `except FetchError`) so the job error is the
  accurate SSRF message — the gate never bypasses `url_guard`.
- **robots.txt fetched via `http_fetcher.fetch` directly** (not `fetch_service`, avoiding gate
  recursion; not stdlib `RobotFileParser.read()`, which does its own blocking unguarded
  `urlopen`). Body parsed with `RobotFileParser.parse(body.splitlines())`. Robots cache keyed by
  `scheme://netloc` origin, TTL via module constant `_ROBOTS_CACHE_TTL_SECONDS = 3600` (no new
  env var — consistent with `_MIN_VISIBLE_TEXT_CHARS`/`_MAX_TOKENS` house style).
- **Render timeout mapped in `browser.render`** (where `render_timeout_seconds`/`page.goto`
  live): catch `PlaywrightTimeoutError` around `page.goto` → `FetchError("render timed out after
  Ns")`. Not transient (render is the terminal attempt, no retry). The `finally: context.close()`
  still runs.

**Gotchas:**
- **`RobotFileParser` "fresh parser disallows everything" trap.** A `RobotFileParser()` that has
  never parsed has `last_checked == 0`, and `can_fetch()` returns **False** in that state (it
  assumes nothing is allowed until robots.txt is read). So the fail-open "allow" case can **not**
  be a blank parser — it is represented as **`None`** in the cache (`check_robots` returns early
  when the parser is `None`). A real parser is built only from a 200 body (where `.parse()` sets
  `last_checked`), so its `can_fetch` works normally. Two tests pin this (404 → allow; a Disallow
  body → block).
- **`SSRFError` is a `FetchError` subclass**, so the robots `except SSRFError: raise` must come
  **before** `except FetchError: return None`, or a blocked host would be silently allowed
  (then re-blocked by the target fetch, but with a less precise message). A test asserts
  `SSRFError` propagates out of `check_robots`.
- **Gate ordering = rate-limit then robots.** If the host is over its cap, robots.txt is never
  fetched (saves a request). A token consumed before a robots `Disallow` raise is minor
  over-counting — accepted/conservative.
- **Existing runner tests needed the new dep.** `run_job` now reads
  `app_state.respectful_client`; the `test_jobs_runner.py` `SimpleNamespace` fake gained a
  pass-through `_PassGate` (no-op `guard`) by default, with an optional raising gate for the two
  new rejection tests. Other suites that run jobs (`test_api_extract`, `test_dashboard`,
  `test_jobs_scheduler`) stub `runner.run_job` entirely, so they never reach the gate — untouched.
- **One `E501`** on a test's inline `RateLimitedError(...)` message — wrapped; ruff then clean.
  `ruff format` reflowed `tests/test_respect.py` (no logic change).

**Verified:**
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .` → 61 files formatted.
- `uv run pytest -q` → **268 passed, 1 skipped** (251 prior + 17 new), exit 0. The skip is the
  Chromium-gated browser integration test; one pre-existing Starlette/httpx TestClient
  deprecation warning, unrelated.
- Confirmed by test: rate limiter passes at the cap, raises `RateLimitedError` over it, rolls
  after 60s (injected clock), and isolates per host; robots allows a non-disallowed path, blocks
  a `Disallow`-matching path, fails open on 404/5xx/`TransientFetchError`, propagates `SSRFError`,
  caches per origin (one fetch for two same-origin checks), and is skipped entirely when
  `RESPECT_ROBOTS=false`; `guard` runs rate-limit then robots; a render `goto` timeout →
  `FetchError` (not the raw Playwright error, context still closed); the runner records a
  `RobotsDisallowedError`/`RateLimitedError` from the gate as a readable job `error` and never
  fetches when robots disallows; lifespan exposes `app.state.respectful_client`.
- Invariants held (grep-verified): `app/fetching/respect.py` imports no LLM SDK / `playwright`
  and no `os`/env; its only network is `http_fetcher.fetch` (→ `url_guard` + pinning + size cap);
  `app.fetching` logger added to `respect.py` + `browser.py`; no new env var.

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

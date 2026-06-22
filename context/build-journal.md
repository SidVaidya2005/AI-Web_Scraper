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

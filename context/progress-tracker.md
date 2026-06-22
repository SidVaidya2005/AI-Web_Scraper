# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 1 — Fetch & Render
**Last completed:** 04 URL safety & SSRF guard (2026-06-22)
**Next:** 05 HTTP fetch (fast path)

**Carry-over into next session:**
- **Features 03 + 04 are uncommitted.** F03 (`app/main.py`, `app/__main__.py`,
  `app/logging.py`, `app/api/health.py`, `tests/test_main.py`, the `SettingsDep` add to
  `app/config.py`) and F04 (`app/fetching/errors.py`, `app/fetching/url_guard.py`,
  `tests/test_url_guard.py`) are both unstaged. F01/F02 are committed on `main`. Commit
  only when asked.
- **F05 consumes the guard via `await`.** `resolve_and_validate(url, *, settings)` and
  `validate(...)` are **`async`** now — the `library-docs.md` httpx example calls them
  without `await`; add it. The fetcher must pin the returned IP (IP-in-URL + `Host`
  header + `extensions={"sni_hostname": host}`) and re-resolve+re-pin every redirect hop.
  `FetchResult` (`app/fetching/models.py`) is referenced by docs but not built yet — it
  lands in F05.
- **Guard DNS is mocked via the `_resolve` seam** (no live network). The
  `gaierror`→`FetchError` mapping is *inside* `_resolve`; to exercise it, patch the running
  loop's `getaddrinfo`, not `_resolve`. Tests pin `allow_private_hosts` explicitly so the
  dev shell can't bleed in.
- **Lifespan is deliberately minimal.** `app.state.job_store` (F13), `browser_manager`
  (F06), and `scheduler` (F15) are **not** wired yet — a comment in `app/main.py` marks
  where they go and the drain-before-browser-close shutdown ordering they'll need. Don't
  treat their absence as a bug.
- **App-level tests must use an allow-listed Host.** `TrustedHostMiddleware` rejects
  TestClient's default `testserver` Host with 400 — pin `base_url="http://127.0.0.1"`.
- **`ALLOWED_HOSTS` parses CSV via `NoDecode` + a before-validator** — any *new* `list`/complex
  setting needs the same treatment, or pydantic-settings' JSON-decode rejects a CSV env value.
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.

---

## Progress

### Phase 0 — Foundation
- [x] 01 Project scaffold & tooling
- [x] 02 Config & settings
- [x] 03 App skeleton + health endpoint

### Phase 1 — Fetch & Render
- [x] 04 URL safety & SSRF guard
- [ ] 05 HTTP fetch (fast path)
- [ ] 06 Browser render (fallback)
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

- **Feature 01 scaffold (2026-06-22):** package skeleton only (`__init__.py` per dir, no module files); **Python pinned to 3.12** via `.python-version` (uv fetched 3.12.13); **hatchling** editable-installs `app` so imports/uvicorn resolve; **one smoke test** dodges pytest's exit-5; ruff `["E","F","I","UP","B"]` + pytest `asyncio_mode="auto"`; CI = `uv sync --frozen` → ruff check → format-check → pytest. Full detail in `build-journal.md`.

- **Feature 04 SSRF guard built (2026-06-22):** `app/fetching/url_guard.py` (`validate` /
  `resolve_and_validate`) + `app/fetching/errors.py` (`FetchError`, `SSRFError(FetchError)`).
  Both functions are **`async`** (`await loop.getaddrinfo` — never blocks the loop);
  **validate-all/pin-first** (any blocked resolved IP rejects the URL, first vetted IP is
  pinned); IPv4-mapped IPv6 unwrapped; `ALLOW_PRIVATE_HOSTS=true` disables only the IP
  block (scheme allow-list always applies). The HTTP-pin / opt-in-render spec rationale is
  in `architecture.md` and archived in `build-journal.md`. Full detail in `build-journal.md`.
- **Scheduler bounded by concurrency AND atomic admission** (15): `MAX_CONCURRENT_JOBS` semaphore + retained task refs + `try_reserve()` (synchronous check-and-increment, no `await` → no TOCTOU) capping in-flight+waiting at `MAX_QUEUED_JOBS`; over cap → `503`/`429`, no job created; `release()` on terminal / failed-create / failed-submit. Admission **closes first on shutdown** (`try_reserve()` → False), and a `submit()` that fails after reserve+create releases the slot **and** terminalizes the job (no `queued` zombie). Shutdown drains **before** the browser closes.
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Feature 02 config (2026-06-22):** `app/config.py` `Settings` (pydantic-settings) reads all 26 vars; per-field `Field(gt=0/ge=0)` positivity + a `model_validator` for `max_concurrent_jobs <= max_queued_jobs <= max_jobs` — fail-fast at construction. `LLM_PROVIDER`/`LOG_LEVEL` are `Literal`, API keys `SecretStr`; `ALLOWED_HOSTS` CSV-parsed via `NoDecode` + before-validator (avoids pydantic-settings JSON-decode). `MAX_CONTENT_CHARS=50000` finalized; API-key presence deferred to provider/registry (F10); `SettingsDep` deferred to F03. Full detail in `build-journal.md`.
- **Feature 03 app skeleton (2026-06-22):** `create_app()` + **minimal deferred lifespan** (settings + logging only; `job_store`/`browser_manager`/`scheduler` deferred to F13/F06/F15 as a comment, no stubs); `TrustedHostMiddleware(ALLOWED_HOSTS)` is the live v1 Host allow-list; `python -m app` honors `HOST`/`PORT`; `SettingsDep` added to `config.py`; `/health` is liveness-only with an inline `HealthResponse`. Full detail in `build-journal.md`.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

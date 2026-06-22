# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 0 — Foundation
**Last completed:** 03 App skeleton + health endpoint (2026-06-22)
**Next:** 04 URL safety & SSRF guard (Phase 1 — Fetch & Render)

**Carry-over into next session:**
- **Feature 03 files are uncommitted** (`app/main.py`, `app/__main__.py`, `app/logging.py`,
  `app/api/health.py`, `tests/test_main.py`, and the `SettingsDep` addition to
  `app/config.py`) — commit only when asked. F01/F02 are committed on `main`.
- **Lifespan is deliberately minimal.** `app.state.job_store` (F13), `browser_manager`
  (F06), and `scheduler` (F15) are **not** wired yet — a comment in `app/main.py` marks
  where they go and the drain-before-browser-close shutdown ordering they'll need. Don't
  treat their absence as a bug.
- **App-level tests must use an allow-listed Host.** `TrustedHostMiddleware` rejects
  TestClient's default `testserver` Host with 400 — pin `base_url="http://127.0.0.1"`.
- **Phase 1 starts with the SSRF guard (04).** `validate(url, *, settings)` +
  `resolve_and_validate(...) -> (host, ip)` returning the vetted IP for pinning; a
  first-class safety feature with no network I/O of its own yet. `ALLOW_PRIVATE_HOSTS`
  gates the private-IP block for tests.
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
- [ ] 04 URL safety & SSRF guard
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

- **SSRF guard is a first-class feature** (04). HTTP path **pins the validated IP per request** — IP-in-URL + `Host` header + `sni_hostname` extension (TLS verifies the hostname, no custom transport) — closing the DNS-rebinding resolve→connect race, with a hard streamed byte cap. Browser path guards **every** connection — `context.route` (HTTP) + `service_workers="block"` (SWs bypass routes) + `route_web_socket` that **blocks all WS** (an accepted rendering limitation — WS can't be vetted/pinned, so pages that hydrate the DOM purely from a socket stream won't fully render) — but **can't pin**, so it carries a documented residual rebinding risk and a best-effort byte cap. Therefore **browser rendering is opt-in** (`render` flag, default off): the default path is HTTP-pinned only and the residual is confined to requests that opt in; Chromium is launched **lazily** on the first render (HTTP-only runs never start it). Proxy = complete fix that would make rendering safe-by-default (follow-up).
- **Scheduler bounded by concurrency AND atomic admission** (15): `MAX_CONCURRENT_JOBS` semaphore + retained task refs + `try_reserve()` (synchronous check-and-increment, no `await` → no TOCTOU) capping in-flight+waiting at `MAX_QUEUED_JOBS`; over cap → `503`/`429`, no job created; `release()` on terminal / failed-create / failed-submit. Admission **closes first on shutdown** (`try_reserve()` → False), and a `submit()` that fails after reserve+create releases the slot **and** terminalizes the job (no `queued` zombie). Shutdown drains **before** the browser closes.
- **Request `output_schema` is JSON Schema with root `type: object`, validated with `jsonschema[format]`** using `Draft202012Validator` + `FORMAT_CHECKER` (plain `jsonschema.validate` ignores `format`) — never `create_model`.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Feature 02 config (2026-06-22):** `app/config.py` `Settings` (pydantic-settings) reads all 26 vars; per-field `Field(gt=0/ge=0)` positivity + a `model_validator` for `max_concurrent_jobs <= max_queued_jobs <= max_jobs` — fail-fast at construction. `LLM_PROVIDER`/`LOG_LEVEL` are `Literal`, API keys `SecretStr`; `ALLOWED_HOSTS` CSV-parsed via `NoDecode` + before-validator (avoids pydantic-settings JSON-decode). `MAX_CONTENT_CHARS=50000` finalized; API-key presence deferred to provider/registry (F10); `SettingsDep` deferred to F03. Full detail in `build-journal.md`.
- **Feature 03 app skeleton (2026-06-22):** `create_app()` + **minimal deferred lifespan** (settings + logging only; `job_store`/`browser_manager`/`scheduler` deferred to F13/F06/F15 as a comment, no stubs); `TrustedHostMiddleware(ALLOWED_HOSTS)` is the live v1 Host allow-list; `python -m app` honors `HOST`/`PORT`; `SettingsDep` added to `config.py`; `/health` is liveness-only with an inline `HealthResponse`. Full detail in `build-journal.md`.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

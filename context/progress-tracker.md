# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 0 — Foundation
**Last completed:** 01 Project scaffold & tooling (2026-06-22)
**Next:** 02 Config & settings

**Carry-over into next session:**
- **Scaffold is uncommitted.** All Feature 01 files (`pyproject.toml`, `.python-version`,
  `uv.lock`, `app/`, `tests/`, `.env.example`, `.github/workflows/ci.yml`) are in the
  working tree but **not committed/pushed** — so **CI has not actually run green yet**.
  First action when committing: branch off `main`, commit the scaffold, push to confirm CI.
- **Feature 02 must finalize `MAX_CONTENT_CHARS`** — `.env.example` uses a provisional
  `50000`; set the authoritative `Settings` default and the `model_validator` relationships
  (`MAX_CONCURRENT_JOBS <= MAX_QUEUED_JOBS <= MAX_JOBS`, positivity) per `code-standards.md`.
- Local Python is 3.14.5 but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.

---

## Progress

### Phase 0 — Foundation
- [x] 01 Project scaffold & tooling
- [ ] 02 Config & settings
- [ ] 03 App skeleton + health endpoint

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
- **Schema conformance = provider `strict` + post-validation**; forcing the tool only guarantees it's called.
- **Result is always an object envelope** (lists under a property key), consistent with the root-object schema rule.
- **The fetch contract returns a `FetchResult`** (html, mode, status, content_type, final_url) so the fallback matrix can branch — not bare HTML. The browser builds it from the **real** `page.goto()` response + `page.url`, never hardcoded `200`/`text/html`/original URL.
- **Settings validate relationships** (`MAX_CONCURRENT_JOBS <= MAX_QUEUED_JOBS <= MAX_JOBS`, positivity) via a `model_validator`, failing fast at startup.
- **Single process / single Uvicorn worker**; `HOST`/`PORT` honored only via the `python -m app` (`app/__main__.py`) entry point.
- **Host-allowlist + Origin checks ship in v1** (cheap DNS-rebinding/CSRF baseline); token-CSRF + auth remain prerequisites for any remote bind.

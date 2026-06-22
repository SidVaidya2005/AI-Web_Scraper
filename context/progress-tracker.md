# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 2 — AI Extraction (complete) → Phase 3 next
**Last completed:** 12 Extraction engine (2026-06-23)
**Next:** 13 In-memory job store (Phase 3 — Jobs & API)

**Carry-over into next session:**
- **F12 built:** `app/extraction/engine.py` `extract(content, *, prompt, schema, provider:
  LLMProvider)` — `normalize_for_strict(schema)` → `provider.extract(...)` →
  `validate_output(raw, schema=schema)` against the **ORIGINAL** schema, wrapping the jsonschema
  `ValidationError` into `ProviderError("extraction did not match schema: …")`. **Provider is
  INJECTED** (engine reads no settings, never calls the registry) — the F14 runner builds it via
  `registry.get_provider(settings, override=request.provider)`. Documented deviation from
  `architecture.md`'s data-flow (annotated in `build-plan.md` F12). Suite **155 passing, 1
  skipped** (149 prior + 6 new). Approved plan: `~/.claude/plans/12-extraction-engine-curried-island.md`.
  **Phase 2 closed.**
- **Next is F13 (In-memory job store):** `app/jobs/models.py` (`Job`, `JobStatus`) +
  `app/jobs/store.py` `JobStore` (`create`/`get`/`list`/`mark_running`/`mark_done`/`mark_error`,
  `asyncio.Lock`, TTL eviction of **terminal** jobs from `finished_at`, `MAX_JOBS` cap,
  newest-first listing). This is also where **`JobResponse` lands in `app/models.py`** (deferred
  from F11 — it needs `Job`/`JobStatus`).
- **F12 → F14 contract (for when the runner is built):** the runner builds the provider via
  `registry.get_provider(settings, override=job.request.provider)` and calls
  `engine.extract(content, prompt=…, schema=job.request.output_schema, provider=provider)`. A
  `ProviderError` (schema mismatch, provider/registry failure) propagates to the runner, the
  error boundary, which records it as a job error.
- **Locked extraction invariants:** provider gets the strict-**normalized** schema; output is
  validated against the **original**; `schema=None` skips validation; engine adds no
  untrusted-content framing (provider owns the system prompt + `<page_content>` delimiter).
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F12 code — `app/extraction/engine.py`,
  `tests/test_extraction_engine.py` (both new); plus these context docs (`progress-tracker.md`,
  `build-journal.md`, `build-plan.md`). HEAD is `a4f3208 2.11-Extraction-schemas`; tree was clean
  before F12. (Reminder: per CLAUDE.md, commits never add a co-author.)
- **OPEN — pending decision (resolve first next session):** commit F12 now, or proceed straight
  to F13? Developer was asked at session end and hadn't answered. F12 is complete and verified
  (155 passing / 1 skipped, ruff clean) — purely the commit-vs-continue call. (HEAD is still
  `a4f3208 2.11-Extraction-schemas`.)

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
- [x] 10 Anthropic provider
- [x] 11 Extraction schemas
- [x] 12 Extraction engine

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

- **Feature 12 Extraction engine built (2026-06-23):** `app/extraction/engine.py`
  `extract(content, *, prompt, schema, provider: LLMProvider)` — `normalize_for_strict(schema)`
  → `provider.extract(...)` → `validate_output` against the **original** schema, wrapping the
  jsonschema `ValidationError` into `ProviderError("extraction did not match schema: …")`. The
  **provider is injected by the F14 runner** (engine reads no settings, never calls the registry)
  — a **documented deviation** from `architecture.md`'s data-flow (annotated in `build-plan.md`
  F12) chosen for a registry-free, trivially-testable engine. `schema=None` skips validation; a
  provider `ProviderError` propagates unchanged (runner is the boundary). **155 passing, 1
  skipped. Phase 2 closed.** (F09 provider-interface decision pruned → `build-journal.md`.)
- **Feature 11 Extraction schemas built (2026-06-23):** `app/extraction/schemas.py` —
  `validate_request_schema` (root `type:object` + a **targeted denylist** of out-of-subset
  keywords → `InvalidSchemaError(ValueError)`), `normalize_for_strict` (deep copy; sets
  `additionalProperties:false` + `required:[all keys]` on every object node with `properties` —
  for the provider's strict tool only), and `validate_output` (`Draft202012Validator` +
  `FORMAT_CHECKER` against the **original** user schema; lets jsonschema `ValidationError`
  propagate for F12 to wrap). The subset walk is structure-aware (`_iter_subschemas`), so a
  property literally named `not` is accepted. `app/models.py` `ExtractRequest` wires the gate via a
  `@field_validator` (→ 422 in F16); **`JobResponse` deferred to F13/F16**. **149 passing, 1
  skipped.** (F08 cleaner decision pruned → `build-journal.md`.)
- **Feature 10 Anthropic provider + registry built (2026-06-22):**
  `app/providers/anthropic_provider.py` (`AnthropicProvider`) does forced tool-use on
  `AsyncAnthropic` (tool `emit_extraction`, `tool_choice` forcing it, untrusted-content system
  prompt + `<page_content>` delimiter, `max_tokens=4096`); model from settings; SDK errors →
  generic `ProviderError` (full detail logged, never `str(exc)`). **Sets `strict: true` when a
  schema is present and passes it through unchanged — strict normalization is deferred to F11.**
  `app/providers/registry.py` `get_provider(settings, *, override=None)` resolves
  `override or settings.llm_provider`; only `"anthropic"` wired (`"openai"`/unknown → `ProviderError`,
  F22), empty key → `ProviderError` at selection. `LLM_TIMEOUT_SECONDS` wired into the client now;
  retries → F21. Test seam = injected fake client (SDK never hit). `anthropic` imported only here.
  **127 passing.** (F06 browser-render decision pruned → `build-journal.md`.)
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

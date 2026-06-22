# Progress Tracker

> **Role:** Live build status — what's done, in progress, and next.
> **Read at the start of every session**; **update after every completed feature.**
> **Relates to:** mirrors `build-plan.md` exactly.

Update this file after every completed feature. Any AI agent reading this should
immediately know what is done, what is in progress, and what is next.

---

## Current Status

**Phase:** Phase 2 — AI Extraction (in progress)
**Last completed:** 10 Anthropic provider (2026-06-22)
**Next:** 11 Extraction schemas (Phase 2 — AI Extraction)

**Carry-over into next session:**
- **F10 built:** `app/providers/anthropic_provider.py` (`AnthropicProvider`) +
  `app/providers/registry.py` (`get_provider(settings, *, override=None)`). First feature to
  import an SDK — `from anthropic import AsyncAnthropic`, confined to that one file. Suite at
  **127 passing** (116 prior + 11 new). Approved plan:
  `~/.claude/plans/feature-10-anthropic-declarative-feather.md`.
- **Next is F11 (Extraction schemas):** `app/extraction/schemas.py` — enforce root
  `type: object` + the supported subset (reject otherwise → 422), **own strict-mode
  normalization** (`additionalProperties:false`, `required`), and validate the LLM dict with
  `Draft202012Validator(..., format_checker=FORMAT_CHECKER)` (not plain `jsonschema.validate`).
  Plus `app/models.py` `ExtractRequest`/`JobResponse`. **F10 deliberately deferred normalization
  to F11** — the F12 engine will normalize the schema *before* calling `provider.extract(...)`.
- **F10 provider contract for F12 to wire:** `provider.extract(*, content, prompt, json_schema)`
  sets `strict: true` when `json_schema is not None` and passes the schema **through unchanged**
  (no normalization in the provider). Registry resolves `override or settings.llm_provider`;
  only `"anthropic"` wired — `"openai"`/unknown → `ProviderError` (F22 adds openai). Empty
  `ANTHROPIC_API_KEY` → `ProviderError` at selection (fail fast). `LLM_TIMEOUT_SECONDS` is
  wired into the client now; retries/timeout→job-error taxonomy stay F21.
- **Provider construction:** `AnthropicProvider(*, api_key, model, timeout, client=None)` —
  takes plain values (registry unwraps `SecretStr`), `client` is the test seam (inject a fake;
  defaults to real `AsyncAnthropic`). `max_tokens=4096` module constant; no `thinking` config.
  Registry constructs per-call (no caching) — provider/client caching is a noted F21+ follow-up.
- **Test seams / isolation:** `tests/test_providers.py` mocks the SDK via an injected fake
  client (no live LLM); `Settings(_env_file=None, anthropic_api_key="test-key", …)` (init
  kwargs outrank env, so pinning is authoritative).
- Local Python is 3.14.x but the project is **pinned to 3.12** via `.python-version`
  (uv fetched 3.12.13) — always work through `uv run`, not the system interpreter.
- **Uncommitted (commit only when asked):** F10 code — `app/providers/anthropic_provider.py`,
  `app/providers/registry.py` (new); `tests/test_providers.py` (modified); plus these context
  docs (`progress-tracker.md`, `build-journal.md`). (Reminder: per CLAUDE.md, commits never add
  a co-author.)
- **OPEN — pending decision (resolve first next session):** commit F10 now, or proceed straight
  to F11? Developer was asked at session end and hadn't answered. F10 is complete and verified
  (127 passing, ruff clean) — this is purely the commit-vs-continue call.
- **Prior OPEN item resolved:** F09 *was* committed (`a296780 2.9-LLM-provider-interface`); the
  "commit F09 now or proceed?" question is moot — it's committed and the tree was clean.

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
- **Feature 09 provider interface built (2026-06-22):** `app/providers/base.py` —
  `ProviderError(RuntimeError)` + a `@runtime_checkable` `LLMProvider` Protocol with one
  async, keyword-only `extract(*, content, prompt, json_schema) -> dict[str, Any]` (object
  envelope; raises `ProviderError`). Interface-only — **no SDK / registry / concrete
  provider** (F10); import from the real path, no `__init__` barrel. `tests/test_providers.py`
  asserts `isinstance(fake, LLMProvider)`, a non-conformer fails it, and `extract()` awaits to
  a `dict`. **Phase 2 begun.** (F05 HTTP-fetch decision pruned → `build-journal.md`.)
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

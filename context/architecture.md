# Architecture

> **Role:** How the system is built — stack, structure, boundaries, data, and the invariants that must never be violated.
> **Read after** `project-overview.md`, before writing any code.
> **Relates to:** the stack here drives `code-standards.md` and `library-docs.md`.

## Stack

| Layer | Tool | Purpose |
| ----- | ---- | ------- |
| Language | Python 3.12+ | Primary language; full type hints, async-first |
| API framework | FastAPI | HTTP API and host for the server-rendered dashboard |
| ASGI server | Uvicorn | Runs the FastAPI app |
| Dashboard UI | Jinja2 templates + HTMX | Server-rendered dashboard; HTMX for live polling without a JS build |
| HTTP fetch | httpx (async) | Fast static-HTML fetch — the primary fetch path |
| Browser render | Playwright (async, Chromium) | Renders JavaScript-heavy pages — the fallback fetch path |
| HTML cleaning | selectolax | Strip boilerplate and reduce HTML to a bounded character budget (coarse cost cap, not token-accurate) before the LLM |
| API models / validation | Pydantic v2 | API request/response models and the in-memory `Job` model (the request's extraction schema is JSON Schema, validated with `jsonschema` — not Pydantic) |
| Output-schema validation | jsonschema | Validate LLM output against the user's JSON Schema (`output_schema`) |
| AI provider (default) | Anthropic SDK | LLM extraction/understanding; default `claude-sonnet-4-6` |
| AI provider (optional) | OpenAI SDK | Second provider behind the same `LLMProvider` interface |
| Config | pydantic-settings | Typed settings loaded from environment / `.env` |
| Jobs | asyncio + in-memory registry | Async job execution and status; no external queue |
| Testing | pytest + pytest-asyncio | Unit and API tests |
| Lint / format | ruff | Linting and formatting |
| Packaging | uv + `pyproject.toml` | Dependency and virtual-env management |

---

## Folder Structure

> **Status: planned / target.** Nothing under `app/`, `templates/`, `static/`, or
> `tests/` exists yet — the repo is currently documentation-only (`CLAUDE.md`,
> `context/`, `LICENSE`, `README.md`). The tree below is the structure to build
> toward; the `## Commands` in `CLAUDE.md` are not runnable until Feature 01
> (scaffold) lands. Create each path as the owning feature in `build-plan.md`
> requires it.

```
AI-Web_Scraper/
├── CLAUDE.md                  → entry point; redirects the agent into context/
├── README.md
├── LICENSE
├── .gitignore                 → .env, __pycache__, .venv, build artifacts
├── pyproject.toml             → dependencies + ruff/pytest config
├── uv.lock                    → pinned dependency lockfile (committed)
├── .env.example               → documented env vars (no real secrets)
├── .github/workflows/ci.yml   → CI: ruff lint/format check + pytest on push
├── context/                   → AI working knowledge (this folder)
├── app/
│   ├── __init__.py
│   ├── __main__.py            → `python -m app` entry point; uvicorn.run(host=settings.host, port=settings.port)
│   ├── main.py                → app factory; lifespan (browser + scheduler); TrustedHost middleware; mounts router, static, templates
│   ├── config.py              → Settings (pydantic-settings); ONLY place env is read
│   ├── logging.py             → logging configuration
│   ├── models.py              → shared API request/response Pydantic models (ExtractRequest, JobResponse, …)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── extract.py         → POST /extract, GET /jobs, GET /jobs/{id}
│   │   └── health.py          → GET /health
│   ├── dashboard/
│   │   ├── __init__.py
│   │   └── routes.py          → server-rendered dashboard pages + HTMX partials
│   ├── fetching/
│   │   ├── __init__.py
│   │   ├── url_guard.py       → SSRF guard: validate/resolve URL, block private/reserved IPs, re-check on redirect
│   │   ├── http_fetcher.py    → httpx fast path (size-capped; calls url_guard)
│   │   ├── browser.py         → Playwright render (uses the shared browser; calls url_guard)
│   │   └── fetch_service.py   → strategy: HTTP first, opt-in browser render; returns FetchResult
│   ├── cleaning/
│   │   ├── __init__.py
│   │   └── cleaner.py         → selectolax boilerplate strip + character-budget trim (lossy)
│   ├── extraction/
│   │   ├── __init__.py
│   │   ├── schemas.py         → normalize request JSON Schema + validate LLM output with jsonschema
│   │   └── engine.py          → orchestrate cleaned content + prompt/schema → validated result
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py            → LLMProvider protocol/ABC + ProviderError
│   │   ├── anthropic_provider.py
│   │   ├── openai_provider.py
│   │   └── registry.py        → pick the provider from config
│   └── jobs/
│       ├── __init__.py
│       ├── models.py          → Job, JobStatus
│       ├── store.py           → in-memory JobStore (dict + TTL eviction + max-count cap)
│       ├── scheduler.py       → bounded concurrency (semaphore), tracked task set, graceful-shutdown drain
│       └── runner.py          → async worker: runs the fetch→clean→extract lifecycle
├── templates/                 → Jinja2 templates
│   ├── base.html
│   ├── index.html             → dashboard: submit form + jobs table mount
│   ├── _jobs_table.html       → HTMX partial: jobs list (polled)
│   └── job_detail.html        → single job result viewer + export links
├── static/
│   └── styles.css
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_fetching.py
    ├── test_cleaning.py
    ├── test_extraction.py
    ├── test_jobs.py
    └── test_api.py
```

---

## System Boundaries

| Folder | Owns |
| ------ | ---- |
| `app/api/` | HTTP/JSON endpoints. Validates input, creates/queries jobs, returns Pydantic response models. **No** scraping, cleaning, or LLM logic; **no** HTML. |
| `app/dashboard/` | Server-rendered HTML pages and HTMX partials. Read-only views over jobs + the submit form. **No** business logic beyond calling the same services the API uses. |
| `app/fetching/` | Getting raw or rendered HTML for a URL. The **only** place `httpx` and Playwright are used. Owns the **SSRF guard** (`url_guard.py`): every target URL is validated and its resolved IP checked before any request, and re-checked after each redirect. **No** AI, no parsing into structured data. |
| `app/cleaning/` | Turning raw HTML into cleaned, character-bounded content (lossy cap, not token-accurate). **No** network, **no** AI, **no** job state. |
| `app/extraction/` | Orchestrating cleaned content + prompt/schema → validated structured data via a provider. Talks to `LLMProvider` only; **never** imports an LLM SDK directly. |
| `app/providers/` | All LLM SDK calls, behind `LLMProvider`. The **only** place `anthropic` / `openai` are imported. |
| `app/jobs/` | Job lifecycle and in-memory state. Owns the job registry, the bounded scheduler (concurrency limit + tracked tasks + shutdown drain), and the async runner. Calls services; contains no HTTP or scraping logic itself. |
| `app/config.py` | Typed settings from environment. The **only** place env vars / `.env` are read. |
| `app/models.py` | Shared API-facing Pydantic models. No logic. |
| `templates/`, `static/` | Presentation assets only. |

---

## Data Flow

### Extraction job (submit)

```
POST /extract  (api/extract.py)
   │  validate ExtractRequest (Pydantic)
   ▼
scheduler.try_reserve()    → atomic admission (sync check-and-increment)
   │  └─ at cap (or draining at shutdown) → 503/429, NO job created
   ▼
JobStore.create(request)   → job_id, status=queued
   │  └─ on failure: scheduler.release(); re-raise
   ▼
scheduler.submit(job_id)   → tracked task under a concurrency semaphore
   │  (never a bare asyncio.create_task: the task ref is retained so it can't be
   │   GC'd mid-flight; excess submissions wait their turn on the semaphore)
   │  └─ on failure: scheduler.release() + mark job error  (see scheduler invariant)
   ▼
202 Accepted  { job_id, status: "queued" }
```

### Job execution (worker)

```
runner.run_job(job_id)
   │  status → running
   ▼
fetch_service.fetch(url, render=job.request.render)   # httpx fast path; Playwright only if render=True; returns FetchResult
   ▼
cleaner.clean(result.html)         # selectolax strip + char-budget trim
   ▼
engine.extract(content, prompt, schema)
   │   provider = registry.get_provider(settings)
   │   raw = provider.extract(content, prompt, json_schema)   # forced tool-use (+ strict)
   │   result = Draft202012Validator(output_schema, format_checker=…).validate(raw) (if schema given)
   ▼
JobStore.mark_done(job_id, result=…, mode=…)
        └─ on any failure: JobStore.mark_error(job_id, error="<message>")   (never raises out of the worker)
```

### Status polling

```
GET /jobs/{id}  → JobStore.get(id)  → JobResponse(status, result | error, mode, timestamps)
Dashboard       → HTMX polls _jobs_table partial every N seconds until every job is terminal
```

### Fetch strategy (inside fetch_service)

```python
# A FetchResult carries everything the matrix needs — not just HTML.
@dataclass(frozen=True)
class FetchResult:
    html: str
    mode: str           # "http" | "browser"
    status: int         # final HTTP status
    content_type: str   # normalized content-type
    final_url: str      # after redirects (already url_guard-validated)
```

```
url_guard.validate(url)                          # SSRF guard FIRST: scheme, resolve host, reject private/reserved IPs
r = http_fetcher.fetch(url)                       # fast path; size-capped, each redirect re-validated → rich result
if r.status_ok and r.is_html and not needs_render(r.html):
    return r                                      # mode="http"
return browser.render(url)                        # Playwright fallback → mode="browser"
```

**Fallback decision matrix** (resolves the ambiguity across docs — this is the
single source of truth). Rendering is **opt-in**: the browser path runs only when
the request set `render: true`. With `render: false` (the default) the HTTP fast
path is the *only* path and the browser is never launched — an outcome that would
otherwise fall back becomes a job `error` instead. When `render: true`, the branch
keys off `FetchResult` fields (`status`, `content_type`) — returning only HTML would
lose the information needed to decide:

| HTTP fast-path outcome | `render: true` | `render: false` (default) |
| ---------------------- | -------------- | ------------------------- |
| 2xx, HTML, passes `needs_render` | return result, `mode="http"` | return result, `mode="http"` |
| 2xx, HTML, fails `needs_render` (tiny/empty/SPA shell) | render → `mode="browser"` | job `error`: "page looks JS-rendered — retry with `render: true`" |
| 2xx, **non-HTML** content-type | render (some sites gate on UA/JS); if render also non-HTML → job `error` | job `error` (non-HTML) |
| **timeout** or transient network error | one bounded retry (`FETCH_MAX_RETRIES`), then render, then job `error` | one bounded retry, then job `error` |
| **non-2xx** (4xx/5xx) | render once; if it also fails → job `error` with the status | job `error` with the status |
| URL rejected by `url_guard` (any path) | immediate job `error`; **never** fetched or rendered | same |

Rendering reads the page with `wait_until="domcontentloaded"` plus a bounded
settle (a short wait for `body` / a configured `RENDER_SETTLE_MS`), **not**
`wait_until="networkidle"` — networkidle is discouraged by Playwright and can
hang on pages with long-polling or analytics beacons.

---

## Data Model

There is **no database**. State lives in an in-memory registry for the life of
the process and is lost on restart.

### `Job` (in-memory, Pydantic model in `app/jobs/models.py`)

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | `str` | UUID4 string; the `job_id` returned to clients |
| `status` | `JobStatus` | enum: `queued` \| `running` \| `done` \| `error` |
| `request` | `ExtractRequest` | the original submission (url, prompt, optional schema, provider override, `render` flag) |
| `mode` | `str \| None` | which fetch path ran: `"http"` or `"browser"`; `None` until fetched |
| `result` | `dict \| None` | structured extraction output; `None` unless `status == done`. **Always a JSON object envelope** — a tool-call's `input` is always an object, so list/scalar extractions come back wrapped under a key (e.g. `{"items": [...]}`). Callers and exporters read the envelope, never a bare top-level list. |
| `error` | `str \| None` | readable failure message; `None` unless `status == error` |
| `created_at` | `datetime` | set on creation (UTC) |
| `started_at` | `datetime \| None` | set when the worker begins |
| `finished_at` | `datetime \| None` | set on terminal state |

### `JobStore` (in-memory registry, `app/jobs/store.py`)

- Backed by a `dict[str, Job]` guarded by an `asyncio.Lock`.
- TTL eviction: **terminal** jobs (`done`/`error`) whose `finished_at` is older than
  `JOB_TTL_SECONDS` are dropped to bound memory. A `MAX_JOBS` cap also evicts the
  oldest **terminal** jobs once exceeded. **`queued`/`running` jobs are never
  evicted** regardless of age.
- Single instance per process, created at startup and injected via FastAPI dependency. **Not** shared across processes or restarts.

### Job lifecycle rules

- **Allowed transitions:** `queued → running → done`, `queued → running → error`,
  and `queued → error` / `running → error` (failure or shutdown). No other
  transitions; terminal states (`done`, `error`) never change.
- **Timestamps:** `created_at` on create, `started_at` on `running`, `finished_at`
  on any terminal state. TTL is measured from `finished_at`.
- **List ordering:** newest first by `created_at` (the dashboard and `GET /jobs`
  rely on this).
- **Shutdown / cancellation:** on lifespan shutdown the scheduler stops accepting
  new work and drains in-flight tasks within a bounded grace period; any job still
  `queued`/`running` at the deadline is marked `error` with a clear "server
  shutdown" / "cancelled" message — it is never left dangling.
- **Single process only.** The registry lives in one process; run with a **single
  Uvicorn worker** (`--workers 1`, the default). Multiple workers would each hold a
  separate store, so a job submitted to one worker would be invisible to polls that
  land on another. `--reload` restarts drop all jobs — acceptable in dev, consistent
  with "no persistence."
- **Binding trust: loopback locally; an explicitly trusted private network when
  deployed.** Locally the service binds loopback (`127.0.0.1`) and is single-user.
  There is **no localhost-only guarantee off-box**: a Render *private service* is
  reachable by other services in the same workspace/region, so deploying widens the
  trust boundary to that private network — running with **no auth is acceptable only
  if you trust everything on that network.** If hosted, run **one** worker/instance
  (in-memory state is **ephemeral** — restarts/redeploys drop all jobs); bind an
  **explicit permitted port** (e.g. `8000`) — `PORT` is **not** auto-set for private
  services, and `10000`/`18012`/`18013`/`19099` are reserved on Render's private
  network; add the service's internal hostname (`<service>-<id>`, the address peers
  use) to `ALLOWED_HOSTS`; pass secrets via env. The container needs Playwright
  Chromium (`playwright install --with-deps chromium`) **only** for `render=true`
  clients — launched lazily, so HTTP-only deployments can omit it. A **public** bind
  stays unsupported until authentication + CSRF tokens + the IP-pinning SSRF egress
  proxy land (all follow-ups). See README → Deployment and `project-overview.md` →
  Security model.

---

## Key Patterns

### FastAPI app factory + Playwright lifespan

A single Chromium browser is launched **lazily on the first `render: true` request**
(serialized by a lock so concurrent first-renders create only one) and reused for
every later render; it is closed on shutdown **only if it was ever launched**, so
HTTP-only runs never start Chromium. The lazy owner is a `BrowserManager`
(`app/fetching/browser.py`; see `library-docs.md`). Templates and static files are
mounted here.

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import extract, health
from app.config import get_settings
from app.dashboard import routes as dashboard
from app.fetching.browser import BrowserManager   # lazy shared-browser owner
from app.jobs.scheduler import Scheduler
from app.jobs.store import JobStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.job_store = JobStore(settings=settings)
    app.state.browser_manager = BrowserManager(settings)   # lazy: no Chromium until first render=true
    app.state.scheduler = Scheduler(app_state=app.state, settings=settings)
    try:
        yield
    finally:
        # Shutdown order matters: stop intake → drain/cancel jobs (they may still be
        # rendering) → THEN close the browser (a no-op if it was never launched).
        await app.state.scheduler.shutdown()        # stop intake, drain within grace, mark survivors error
        await app.state.browser_manager.aclose()    # closes browser/playwright iff launched


def create_app() -> FastAPI:
    app = FastAPI(title="AI-Web-Scraper", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.state.templates = Jinja2Templates(directory="templates")
    app.include_router(health.router)
    app.include_router(extract.router)
    app.include_router(dashboard.router)
    return app


app = create_app()
```

**`/health` semantics:** a plain **liveness** check — returns `200 {"status": "ok"}`
whenever the process is up. It does **not** probe the browser, provider keys, or
network (readiness is out of scope for a localhost tool). If a readiness signal is
ever needed, add a separate `/ready` rather than overloading `/health`.

**`HOST` / `PORT`:** the documented `uvicorn app.main:app` command does **not** read
the `HOST`/`PORT` settings — pass them to uvicorn (`--host`/`--port`) or run via a
programmatic `python -m app` entry point that calls `uvicorn.run(host=settings.host,
port=settings.port)`. Provide the `__main__` entry point so the settings are
actually honored; don't leave them as dead config.

### LLMProvider interface + forced tool-use extraction

Every provider implements one method and returns a plain `dict`. Structured
output is obtained by forcing a single tool whose `input_schema` is the
user-supplied JSON Schema, passed **directly** (no Pydantic model is built from
it). On Anthropic, set `strict: true` on the tool when the schema fits the
supported subset; on OpenAI, use strict function calling — both make the model's
tool arguments conform to the schema. Forcing the tool only guarantees the tool
is *called*; conformance comes from `strict`, and is enforced regardless by
re-validating the returned dict against the same JSON Schema in
`app/extraction/` before the job is marked `done` (see `library-docs.md` →
Pydantic / `jsonschema`).

```python
# app/providers/base.py
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Raised when an LLM provider call fails or returns unusable output."""


class LLMProvider(Protocol):
    async def extract(
        self,
        *,
        content: str,
        prompt: str,
        json_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Return structured data extracted from `content` per `prompt`/`json_schema`."""
        ...
```

### Async fetch with opt-in browser rendering

```python
# app/fetching/fetch_service.py
async def fetch(url: str, *, browser_manager, settings, render: bool = False) -> FetchResult:
    r = await http_fetcher.fetch(url, settings=settings)   # rich result (status, content_type, …)
    if r.status_ok and r.is_html and not needs_render(r.html):
        return r                                            # mode="http"
    if not render:                                          # opt-in: never launch the browser unasked
        raise FetchError("HTTP result insufficient; retry with render=true")
    browser = await browser_manager.get()                  # lazy launch on first real render
    return await browser_render(url, browser=browser, settings=settings)  # FetchResult w/ REAL metadata
```

Both `http_fetcher.fetch` and `browser.render` return a `FetchResult` (the browser
one built from the `page.goto()` response + `page.url` — **never** hardcoded
`200`/`text/html`/original URL), so `fetch_service` can apply the decision matrix
and the runner reads `result.mode` for the job's `mode` field.

### In-memory JobStore + bounded scheduler

The endpoint never awaits the work; it hands the job to the scheduler and returns.
Two bounds, not one:

1. **Concurrency** — `run_job` runs under a `MAX_CONCURRENT_JOBS` semaphore, with a
   **strong reference** held to each task (a bare `asyncio.create_task(...)` whose
   result is discarded can be garbage-collected mid-flight — a documented asyncio
   footgun).
2. **Admission (atomic)** — a semaphore alone is *not* bounded: every accepted
   submission still creates a retained waiting task, and `queued`/`running` jobs are
   never evicted, so unbounded submissions = unbounded memory. The scheduler caps the
   total of in-flight + waiting jobs at `MAX_QUEUED_JOBS` via **`try_reserve()`** — a
   *synchronous* check-and-increment (no `await` between check and increment, so it
   can't interleave on the event loop). A separate `has_capacity()` + `submit()`
   would be a **TOCTOU race** — the `await store.create(...)` between them lets a
   second request slip through and exceed the cap. On a failed reservation the API
   returns **`503`** (or `429` + `Retry-After`) and no job is created; the scheduler
   `release()`s the slot when the job reaches a terminal state (or if `create()` fails).

The worker still owns all error handling and must never let an exception escape.

```python
# app/api/extract.py (handler excerpt)
@router.post("/extract", status_code=202, response_model=JobResponse)
async def submit(req: ExtractRequest, request: Request) -> JobResponse:
    scheduler = request.app.state.scheduler
    if not scheduler.try_reserve():                   # atomic admission — no TOCTOU
        raise HTTPException(status_code=503, detail="server at capacity, retry shortly")
    store: JobStore = request.app.state.job_store
    try:
        job = await store.create(req)
    except BaseException:
        scheduler.release()                           # roll back the reservation
        raise
    try:
        scheduler.submit(job.id)                      # consumes reservation; concurrency-capped
    except SchedulerShuttingDown:                     # submit() only rejects while draining at shutdown
        scheduler.release()                           # release the slot...
        await store.mark_error(job.id, error="server shutting down")  # ...and terminalize (no queued zombie)
        raise HTTPException(status_code=503, detail="server shutting down, retry shortly")
    return JobResponse.from_job(job)
```

### Request schema → provider input + result validation

The request `output_schema` is a **JSON Schema document** (a dict over the wire),
**root `type: "object"`** (a tool call's args are always an object). It is **not**
turned into a Pydantic model with `create_model()` — `create_model()` takes Python
field definitions, not arbitrary nested JSON Schema. Instead:

```python
# app/extraction/schemas.py
from jsonschema import Draft202012Validator  # from jsonschema[format]

# 0) At submit time: reject a root-non-object or out-of-subset schema (422).
# 1) Pass the user's JSON Schema straight through as the tool input_schema.
#    A provider-side normalizer fills the strict-mode requirements
#    (additionalProperties: false, required) where the subset allows.
# 2) Validate the LLM's returned dict against the SAME schema, WITH format checks:
#    Draft202012Validator(user_schema,
#        format_checker=Draft202012Validator.FORMAT_CHECKER).validate(raw)
#    (plain jsonschema.validate(...) ignores `format`.) Failure → readable job error.
```

The supported JSON-Schema subset (root object, no recursion/bounds) and
normalization rules live in `library-docs.md` (Pydantic / `jsonschema` section).

---

## Invariants

- All LLM SDK imports (`anthropic`, `openai`) live **only** in `app/providers/`; every other module talks to `LLMProvider`.
- Every LLM call goes through a provider chosen by `app/providers/registry.py` from config; model ids are read from settings, never hardcoded outside `config.py`.
- `app/config.py` is the **only** place environment variables or `.env` are read; no `os.environ` access or secret/URL literals anywhere else.
- **Target-page** network I/O — fetching the user's URL via `httpx` or Playwright — lives **only** in `app/fetching/`. (LLM-provider API calls are a separate, outbound concern and live in `app/providers/`.) `app/cleaning/` and `app/extraction/` never touch the network at all.
- **SSRF guard is mandatory and runs before any fetch.** Every user-supplied URL is validated in `app/fetching/url_guard.py`: allow only `http`/`https`, resolve the host, and reject loopback / private / link-local / reserved / cloud-metadata (`169.254.169.254`) addresses. Re-validate the resolved IP after **every** redirect. Cap the response body at `MAX_RESPONSE_BYTES` — a **hard, pre-buffer streamed cap on the HTTP path**; the browser path enforces the same limit only on a **best-effort** basis (see the DNS-rebinding invariant below). A URL that fails the guard is never fetched or rendered.
- **DNS-rebinding (resolve→connect TOCTOU) is mitigated by IP-pinning on the HTTP path, and is a documented residual on the browser path.** Resolving in the guard and then letting httpx/Chromium re-resolve at connect time is a race — the attacker can answer public to the guard and private to the real connection. So the guarantee is precise, not absolute: `url_guard.resolve_and_validate()` returns the vetted IP; the **HTTP fetcher connects to that exact IP** (preserving the `Host` header + TLS SNI), so the byte stream comes from the validated address. The **browser path cannot pin** without a proxy, so it re-validates each request URL (still a resolve race) and is documented as **residual DNS-rebinding risk**; a byte-counting/IP-pinning egress proxy in front of both fetchers is the complete fix and a hardening follow-up. Do not claim "never fetches a private IP" for the browser path.
- **Jobs run under a bounded scheduler with atomic admission control.** Background work is launched via `app/jobs/scheduler.py`: a `MAX_CONCURRENT_JOBS` semaphore caps concurrency, a retained task set prevents GC of in-flight tasks (never a fire-and-forget `asyncio.create_task`), and a `MAX_QUEUED_JOBS` cap on in-flight + waiting jobs **rejects** excess submissions (API → `503`/`429`) so memory stays bounded — a semaphore alone is not enough, since waiting tasks and their `queued` jobs accumulate. Admission is reserved with a **synchronous, atomic `try_reserve()`** (no `await` between the capacity check and the increment) — a `has_capacity()` then `await create()` then `submit()` sequence is a TOCTOU race that overshoots the cap. The slot is `release()`d on terminal state, a failed `create()`, or a failed `submit()`. **Admission closes first on shutdown:** once draining begins, `try_reserve()` returns False, so no new job is created after shutdown starts — the normal path can't strand a job. Because `submit()` only schedules an already-reserved task, its sole realistic failure is shutdown, where it raises a specific `SchedulerShuttingDown`; on that exception the handler must `release()` the slot **and** mark the just-created job `error` (via `mark_error`, giving it a `finished_at`), so a reserved-then-created job can never linger `queued` forever or leak its slot. (Catch that specific type, not a broad `BaseException`.) On shutdown, in-flight tasks are drained within a grace period and any non-terminal job is marked `error`.
- **Scraped page content is untrusted LLM input.** Treat it as data, never instructions: send it after a clear delimiter under a system prompt that says page content may try to issue instructions and must be ignored; rely on the forced tool + schema for output shape. Page-supplied text never changes the extraction contract.
- `app/cleaning/` and `app/extraction/` never read or mutate job state; only `app/jobs/` does.
- The job registry is **in-memory only**. Never assume jobs survive a restart, and never introduce a database without first updating this file and `project-overview.md`.
- Exactly one Chromium browser exists, **launched lazily on the first `render: true` request** (under a lock so concurrent first-renders create only one) and reused; never launch a browser per request, and **never at startup** — HTTP-only runs (and `render: false` requests) must not start Chromium. It is closed on shutdown only if it was launched.
- All I/O is `async`; never call blocking network/browser APIs from a sync path, and never block the event loop (offload CPU-bound parsing with `run_in_executor` if it becomes heavy).
- The job worker (`run_job`) handles all of its own errors and sets `status=error`; an exception must never escape it or crash other in-flight jobs.
- API endpoints return the declared Pydantic `response_model`; when a request supplies a schema, the result is validated against it before the job is marked `done`.
- The service binds **loopback (`127.0.0.1`) locally** and ships with **no auth**, and runs as a **single process / single Uvicorn worker** (the in-memory store demands it). It is **not localhost-only off-box**: a deployment binds a private network and is reachable by peers there, so no-auth is acceptable only on an **explicitly trusted private network** (see "Binding trust" above) — never a public bind. **v1 baseline browser-facing defenses ship in-process:** a Host-header allow-list (`TrustedHostMiddleware`, `ALLOWED_HOSTS`) and an Origin check on state-changing routes (cheap defenses against DNS-rebinding / a malicious page driving `POST /extract`). Token-based CSRF and real authentication remain out of scope; never expose the service publicly or add a remote bind without adding those first (see `project-overview.md` → Security model).
- Untrusted extracted content rendered in the dashboard is **always escaped** (Jinja2 autoescaping on; never `| safe` on result/error text) — a scraped page must not be able to inject HTML/JS into the dashboard.
- Be a respectful client: send the configured descriptive `USER_AGENT`, enforce fetch/render timeouts, and honor configured rate limits. No anti-bot evasion, CAPTCHA solving, or login automation.
- Build only what the current `build-plan.md` feature requires.

# Project Overview

> **Role:** Product source of truth — what this product is, who it's for, what's in and out of scope.
> **Read first**, before any other context file.
> **Relates to:** scope drives `build-plan.md`; progress tracked in `progress-tracker.md`.

## About the Project

AI-Web-Scraper is an intelligent web data extraction service. You give it a URL
and a description of what you want ("get every product's name, price, and stock
status"), and it fetches the page, renders JavaScript when needed, cleans the
HTML down to its meaningful content, and uses an LLM to return that content as
structured JSON. It runs as a single Python (FastAPI) application that exposes
both an HTTP API and a thin built-in dashboard for submitting jobs and viewing
results.

## The Problem It Solves

Traditional scrapers break the moment a site changes its markup, and they
require hand-written CSS/XPath selectors per site. People who just want data end
up writing and maintaining brittle, site-specific scripts, or copy-pasting by
hand. AI-Web-Scraper removes the selector-writing step: you describe the data in
plain language (optionally pinning an exact schema), and the LLM adapts to
whatever HTML the page actually serves — so the same request works across many
different sites without bespoke code.

## Entry Points

This is an API service with a thin dashboard, not a multi-page app. The
top-level entry points are:

- **`POST /extract`** — submit an extraction job (URL + prompt + optional schema + optional `render` flag); returns a `job_id` immediately.
- **`GET /jobs/{job_id}`** — poll a single job's status and, once finished, its result or error.
- **`GET /jobs`** — list jobs from the current process session.
- **`GET /health`** — liveness check (process up → `200`; does not probe browser/providers).
- **`GET /` (dashboard)** — server-rendered page: submit form + live jobs table.
- **`GET /jobs/{job_id}/view`** — server-rendered detail page for one job's result/error.
- **`GET /jobs/{job_id}/export?format=json|csv`** — download a finished job's result.

## Navigation

The dashboard's main page at `/` holds a job-submission form and a live jobs
table that polls for status via HTMX. Each job links to a **separate detail page**
(`GET /jobs/{id}/view`) showing its structured result (or error) and export
buttons — not an inline expandable row. There is no login flow — the service is
intended to run locally and is unauthenticated (see Security model below).

## Core User Flow

### 1. Describe the extraction

The user supplies a target URL, a natural-language prompt describing the data
they want, optionally a **JSON Schema** (sent as JSON under `output_schema`) to
enforce exact field names and types, and optionally a **`render` flag** to opt in to
headless-browser rendering for JavaScript-heavy pages (default off — see Security
model for why it's not automatic). They submit via the dashboard form or
`POST /extract`. (A Python Pydantic class can't travel over HTTP — the wire
contract is JSON Schema; see `library-docs.md` for the supported subset.)

### 2. Job is accepted

The service validates the request, creates a job in the in-memory registry with
status `queued`, schedules it to run on a background worker, and immediately
returns a `job_id`. The user is not blocked while the page is fetched.

### 3. Fetch and render

The worker fetches the page over HTTP first (fast path). If the request opted in
with `render: true` and the page looks incomplete or JavaScript-driven, it renders
with a headless browser (Playwright) before reading its HTML. With `render: false`
(the default) the browser is never launched — a page that needs rendering returns a
job error suggesting a retry with `render: true` (see Security model for the
rationale).

### 4. Clean and understand

The rendered HTML is stripped of boilerplate (nav, scripts, styles, ads) and
trimmed to a bounded character budget (a coarse cost cap, not token-accurate; see
`library-docs.md`). The cleaned content, the prompt, and the optional schema are
sent to the configured LLM provider, which returns structured data.

### 5. Validate and deliver

If a schema was supplied, the result is validated against it. The job is marked
`done` with its result (or `error` with a message). The dashboard's live table
flips the job to done, and the user opens it to view or export the JSON/CSV.

## Data Architecture

All data is held **in memory for the lifetime of the running process** — there
is no database. Nothing persists across restarts. Because the registry is
in-process, the service runs as a **single process / single Uvicorn worker**;
multiple workers would each keep a separate store and polls could miss jobs.

### Jobs

Each submission becomes a Job record holding its id, status, the original
request, the fetch mode used (http vs browser), the structured result or error,
and timestamps. Jobs live in an in-memory registry (a dictionary with TTL-based
eviction) and back both the polling endpoints and the dashboard.

### Extraction schemas

When a request includes a JSON Schema, it is passed straight to the LLM provider
as the tool's `input_schema` and used to validate the returned data with the
`jsonschema` library (it is **not** converted into a Pydantic model). Schemas are
request-scoped and ephemeral — not saved or reused across jobs. The result is
always a JSON **object**; a list extraction comes back wrapped under a key (e.g.
`{"items": [...]}`), since a tool call's arguments are always an object.

## Features In Scope

- Single-URL extraction: fetch, render-if-needed, clean, LLM-extract, return JSON.
- Fast HTTP fetch with **opt-in** headless-browser (Playwright) rendering for JS-heavy pages (`render` flag, default off — see Security model).
- HTML cleaning / content reduction to keep token usage and cost down.
- Prompt-based extraction with an optional JSON Schema (root `type: object`) for typed, validated output.
- Pluggable LLM provider layer (Anthropic default; OpenAI as a second provider) selected by config.
- Asynchronous job execution with a `job_id` and status-polling endpoints.
- In-memory job registry exposing list and detail views.
- Thin server-rendered dashboard (Jinja + HTMX): submit form, live jobs table, result viewer, JSON/CSV export.
- Per-request timeouts, retries, and clear error reporting on jobs.

## Features Out of Scope

- Any persistent database or job history surviving a restart.
- User accounts, authentication, or multi-tenant data isolation (loopback-local and unauthenticated by default; deploy only to a trusted private network — see Deployment).
- Multi-page crawling / site spidering — one URL per job for now.
- Scheduled or recurring scrapes.
- A distributed task queue (Redis/Celery) — jobs run in-process.
- Proxy rotation, CAPTCHA solving, anti-bot evasion, or authenticated-session/login automation.
- A separate single-page-app frontend (the dashboard is intentionally thin and server-rendered).
- Real-time / WebSocket-driven content: WebSockets are blocked during render for SSRF safety, so a page that populates its DOM purely from a socket stream won't fully render.
- Public / multi-tenant hosting: loopback/local by default, and **not localhost-only off-box** — any deployment must be a **private service on an explicitly trusted network** (reachable by workspace peers; see README → Deployment), and a public bind needs authentication + CSRF tokens + an SSRF egress proxy first.

## Security model & responsible use

The service is **loopback-bound and unauthenticated by design** for local single-user
use (single process). It is **not localhost-only once deployed** — a hosted private
service is reachable by trusted private-network peers (see `architecture.md` → Binding
trust and README → Deployment). Even locally, loopback alone is not a complete security
model, so the threats below are addressed or explicitly accepted:

- **SSRF (addressed — with a precise, not absolute, guarantee).** The product
  fetches a user-supplied URL server-side, which is textbook SSRF — and running next to
  localhost/cloud-metadata endpoints makes it worse, not better. Every URL passes an
  SSRF guard before any fetch: scheme allow-list, host resolution, and blocking of
  loopback / private / link-local / reserved / metadata (`169.254.169.254`) addresses,
  re-checked on every redirect, with a response-size cap. The **HTTP fast path pins the
  validated IP** (connects to the exact address it checked), closing the DNS-rebinding
  resolve→connect race; the **browser path re-validates each request but cannot pin**,
  so it carries a documented residual rebinding risk. Because of that, **browser
  rendering is opt-in** (`render: true`, default off): the default path is HTTP-pinned
  only, and the residual is confined to requests that explicitly opt in. A
  byte-counting/IP-pinning egress proxy is the complete fix that would let rendering be
  safe-by-default — a hardening follow-up. See `architecture.md` → Invariants.
- **Prompt injection (addressed — bounded).** Scraped page content is untrusted LLM
  input. It is framed as data (system prompt + delimiter) and output is constrained to
  the tool schema. Impact is bounded — worst case is bad extracted data, not code
  execution — but the defense is still required.
- **Untrusted content in the dashboard (addressed).** Result/error text is rendered
  with Jinja2 autoescaping on; never `| safe`.
- **Host / DNS-rebinding (addressed — v1 baseline).** A local unauthenticated
  service is reachable by any page the user's browser loads, and DNS-rebinding can make
  a remote attacker look same-origin. Host-header allow-listing (`TrustedHostMiddleware`
  with `ALLOWED_HOSTS = 127.0.0.1,localhost`) and an **Origin check on state-changing
  requests** are nearly free, so they ship in v1 — a malicious page can't quietly drive
  `POST /extract` to burn scraping/LLM resources.
- **CSRF tokens / full auth (out of scope, documented).** Token-based CSRF and real
  authentication remain out of scope for the local tool; the Host/Origin checks above are
  the v1 mitigation. Do not expose the service remotely without first adding
  authentication and CSRF tokens.

**Responsible scraping.** Send the configured descriptive `USER_AGENT`, enforce
timeouts, and honor configured rate limits. **robots.txt** is checked and honored by
default (a documented decision; overridable only via config for sites the operator
owns). No anti-bot evasion, CAPTCHA solving, proxy rotation, or login automation.
Users are responsible for the legality of scraping a given site (terms, copyright,
personal data) — surfaced as a README disclaimer.

## Target User

Developers and technical analysts who need structured data out of arbitrary web
pages without writing and maintaining per-site scrapers. They are comfortable
calling an HTTP API or running a local service, and they value adapting to
markup changes via prompts over hand-tuned selectors.

## Success Criteria

- A `POST /extract` with a URL and prompt returns a `job_id`, and polling that job yields valid structured JSON for a typical content page.
- A JavaScript-rendered (SPA) page that returns empty content over plain HTTP is successfully extracted when submitted with `render: true` (Playwright renders it); the same page submitted with `render: false` returns a job error hinting to retry with rendering, and never launches the browser.
- When a request includes a schema, every successful result validates against that schema; schema violations surface as a clear job error rather than malformed output.
- Switching `LLM_PROVIDER` between `anthropic` and `openai` requires no code change and produces results in the same response shape.
- The dashboard can submit a job, show it move queued → running → done live, and export the result as JSON and CSV.
- A fetch/render/LLM failure marks the job `error` with a readable message and never crashes the server or other in-flight jobs.
- A URL pointing at a private/reserved/metadata address (e.g. `http://169.254.169.254/`, `http://localhost/`) is rejected by the SSRF guard as a job `error` and is never fetched or rendered — including via a redirect from a public URL.
- An oversized response on the HTTP fast path is **hard-capped** at `MAX_RESPONSE_BYTES` (streamed, before buffering) and fails cleanly rather than exhausting memory; the browser path enforces the same limit on a best-effort basis.
- Submitting more jobs than `MAX_CONCURRENT_JOBS` runs them under the cap without dropping tasks or crashing; a shutdown mid-run drains in-flight jobs and marks any survivor `error`.
- Tests are deterministic: LLM providers are mocked and pages come from local HTML fixtures (including SPA-shell, oversized, redirecting, and hostile fixtures) — no live network or real LLM calls in the suite.

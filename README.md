# AI-Web-Scraper

An intelligent web data extraction service: give it a URL and a natural-language
description of what you want, and it fetches the page, renders JavaScript when
needed, cleans the HTML, and uses an LLM to return the content as structured
JSON — exposed as a FastAPI service with a thin built-in dashboard.

> **Status: in design / not yet built.** This repository currently holds the
> project's working docs only. The source tree described in `context/architecture.md`
> is the target structure; the commands below are runnable once Feature 01
> (scaffold) lands. See `context/progress-tracker.md` for current status.

## How it works

You describe the data in plain language (optionally pinning an exact JSON Schema),
and the LLM adapts to whatever HTML the page serves — so the same request works
across many sites without per-site selectors. Jobs run asynchronously in memory;
you submit a job, poll its status, and read or export the result.

- `POST /extract` — submit a job (URL + prompt + optional `output_schema`) → `job_id`
- `GET /jobs/{id}` / `GET /jobs` — poll / list jobs
- `GET /` — dashboard (submit form + live jobs table); `GET /jobs/{id}/view` — detail
- `GET /health` — liveness

## Quickstart (after scaffold)

```bash
uv sync                              # install dependencies
uv run playwright install chromium   # one-time; only if you use render=true (launched lazily, skip for HTTP-only)
cp .env.example .env                 # set ANTHROPIC_API_KEY (or OPENAI_API_KEY)
uv run uvicorn app.main:app --reload # run API + dashboard on 127.0.0.1:8000
uv run pytest                        # run the test suite
uv run ruff check . && uv run ruff format .
```

The service binds to **localhost only** and ships with **no authentication**. Run a
**single worker** — job state lives in memory in one process and is lost on restart.

## Deployment

Locally the service binds **loopback (`127.0.0.1`) and runs unauthenticated**. That is
**not** a localhost guarantee once deployed: a hosted **private service** (e.g. on
**Render.com**) is reachable by other services in the same workspace/region, so
deploying widens the trust boundary from your machine to that private network. Running
without auth is acceptable **only if you trust everything on that network**. It is
never safe to expose publicly as-is (no auth/CSRF, in-memory single-process state,
residual browser-path SSRF). Run it as a **private service only** — never a public web
service. Required settings:

- **Single worker / one instance.** Job state is in-memory; multiple workers or
  instances can't see each other's jobs, and every restart drops all jobs (no
  persistence).
- **Bind an explicit, permitted port.** Render does **not** set `PORT` for private
  services, and `10000`/`18012`/`18013`/`19099` are reserved on the private network —
  bind a normal port such as `8000`:
  `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`. Peers reach it at the
  internal address `<service>-<id>:8000` (Dashboard → Connect → Internal).
- **`ALLOWED_HOSTS`.** Add the service's internal hostname (`<service>-<id>`) so the
  Host allow-list accepts private-network requests and rejects others.
- **Chromium only if you render.** The image needs Playwright's Chromium
  (`playwright install --with-deps chromium`) only if clients use `render=true`;
  HTTP-only deployments can skip it (it's launched lazily).
- **Secrets via env.** Provide `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` and any overrides
  as environment variables (read only in `app/config.py`).

**Before any public bind**, add authentication, CSRF tokens, and the IP-pinning egress
proxy (browser-path SSRF) — all currently follow-ups. Until then, public deployment is
unsupported.

## Documentation

The `context/` folder is the source of truth — read it before changing code:
`project-overview.md`, `architecture.md` (and its invariants), `code-standards.md`,
`library-docs.md`, `build-plan.md`, `progress-tracker.md`.

## Responsible use

This tool fetches arbitrary user-supplied URLs server-side. It enforces an SSRF
guard on every request — a scheme allow-list and blocking of private / reserved /
metadata addresses, re-checked on each redirect — plus response-size caps, request
timeouts, and a descriptive User-Agent, and it honors `robots.txt` and configured
rate limits by default.

**The SSRF protection is precise, not absolute.** The HTTP fast path pins the
validated IP (closing the DNS-rebinding resolve→connect race) and hard-caps the
response size. Headless-browser rendering **cannot** pin, so it carries a **residual
DNS-rebinding risk** and only a best-effort size cap — which is why it is **opt-in**
(`render: true`, off by default): the default path is HTTP-pinned only, and the
residual is confined to requests that explicitly enable rendering. Because the
service is **loopback-bound and unauthenticated** locally, that residual is accepted
for local, single-user use — **do not expose it to untrusted networks or users**, and
when deployed treat the private network as part of the trust boundary (see Deployment).
See `context/project-overview.md` → Security model for the full threat model.

It does **not** perform anti-bot evasion, CAPTCHA solving, or login automation. You
are responsible for complying with each target site's terms of service, copyright,
and applicable data-protection law before scraping it.

## License

See [LICENSE](LICENSE).

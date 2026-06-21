# AI-Web-Scraper

An intelligent web data extraction service: give it a URL and a description of
what you want, and it fetches, renders (when needed), cleans, and uses an LLM to
return the page's content as structured JSON — exposed as a FastAPI service with
a thin built-in dashboard.

## Project context lives in `context/`

The `context/` folder is the source of truth for this project. **Read it before
writing any code**, and keep it current as you work. Read in this order:

1. **`context/project-overview.md`** — what the product is, who it's for, what's in and out of scope.
2. **`context/architecture.md`** — stack, folder structure, system boundaries, data model, and the **invariants you must never violate**.
3. **`context/code-standards.md`** — the rules every change must follow.
4. **`context/library-docs.md`** — project-specific usage patterns for each library (read the relevant section before using one).
5. **`context/build-plan.md`** — the ordered phases and features to build.
6. **`context/progress-tracker.md`** — what's done, in progress, and next.

## Standing rules

- **Read `context/` first.** Never assume — verify against `project-overview.md` and `architecture.md`.
- **Obey the invariants** in `architecture.md`. They are non-negotiable (provider isolation; target-page-network-only-in-`fetching` with a mandatory SSRF guard; env-only-in-`config`; in-memory job state on a single worker; single shared browser; bounded job scheduler — no fire-and-forget tasks; untrusted page content treated as data; loopback-local/no-auth — not localhost-only off-box, so deploy only to an explicitly trusted private network).
- **Follow `code-standards.md`** on every change.
- **For libraries**, follow the authority order: **Context7** (`resolve-library-id` → `query-docs`) → skills → `context/library-docs.md` → general knowledge. If Context7 has no match, use web search for official docs — never rely on training-data memory for API shapes. For Claude/Anthropic model ids and API specifics, use the `claude-api` skill.
- **Stay in scope.** Build only what the current feature in `build-plan.md` requires.
- **Update `progress-tracker.md`** after every completed feature — check the box, set current status, and add the single most important decision to "Key Decisions" (cap ~10 bullets).
- **Archive detail in `build-journal.md`** — after each feature, append a dated entry with full decisions, gotchas, and verification results. Prune `progress-tracker.md` "Key Decisions" into here when it exceeds ~10 bullets. Consult it when revisiting a completed feature, investigating a regression, or making a decision that might conflict with past work.

## Commands

- `uv sync` — install dependencies into the project environment.
- `uv run playwright install chromium` — install the headless browser used by **opt-in** rendering (one-time; only needed if you use `render=true` — Chromium is launched lazily, so HTTP-only runs can skip this).
- `uv run uvicorn app.main:app --reload` — run the API + dashboard locally (binds to `127.0.0.1`).
- `uv run pytest` — run the test suite.
- `uv run ruff check .` / `uv run ruff format .` — lint and format.

## Tooling notes

- **Context7 MCP** is available for current library docs (FastAPI, Playwright, Anthropic, Pydantic, httpx, etc.) — prefer it over memory for any API shape.
- The **`claude-api` skill** is the reference for Claude model ids, pricing, and API parameters.

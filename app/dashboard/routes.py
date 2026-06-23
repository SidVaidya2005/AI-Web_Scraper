"""Server-rendered dashboard: the shell, the submit form, and its POST handler.

`GET /` renders the form + the live-jobs polling container (F18 fills the container).
`POST /submit` is form-encoded (not the JSON `/extract` route): it builds the same
`ExtractRequest` the API uses, admits it through the shared `enqueue` helper, and
returns an HTML fragment — a success note that re-arms polling (out-of-band swap of
`#jobs`), or an inline error. No scraping/cleaning/LLM logic lives here.
"""

import json
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.api.security import require_trusted_origin
from app.dashboard import export
from app.jobs.scheduler import SchedulerShuttingDown
from app.jobs.submission import AtCapacityError, enqueue
from app.models import ExtractRequest

router = APIRouter(tags=["dashboard"])

_BUSY_MESSAGE = "Server is at capacity — please retry in a few seconds."
_SHUTDOWN_MESSAGE = "Server is shutting down — please retry shortly."
_STOP_POLLING_STATUS = 286  # htmx: halt the #jobs every-2s poll

# Maps the ?format value to its (media type, serializer). The route's Literal keeps
# the key total, so the lookup never misses.
_EXPORTERS = {
    "json": ("application/json; charset=utf-8", export.result_to_json),
    "csv": ("text/csv; charset=utf-8", export.result_to_csv),
}


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _readable_input_error(exc: Exception) -> str:
    """Turn a parse/validation failure into a short, user-safe message."""
    if isinstance(exc, json.JSONDecodeError):
        return "Output schema must be valid JSON."
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        msg = first.get("msg", "invalid value")
        return f"Invalid {loc}: {msg}" if loc else msg
    return "Invalid input."


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the dashboard shell: submit form + the live-jobs polling container."""
    return _templates(request).TemplateResponse(request, "index.html", {})


@router.get("/partials/jobs", response_class=HTMLResponse)
async def jobs_partial(request: Request) -> HTMLResponse:
    """Render the live jobs table; 286 stops polling once all jobs are terminal/empty.

    Returns the table that swaps into the #jobs container's innerHTML. HTTP 286 is
    htmx's "stop polling" signal — htmx still swaps the body (286 is in its default
    2xx/3xx swap range), so the final poll shows terminal rows before the poll halts.
    A later submit re-arms the poller (F17). `all([])` is True, so the empty table
    stops polling too.
    """
    jobs = await request.app.state.job_store.list()
    stop = all(job.is_terminal for job in jobs)
    return _templates(request).TemplateResponse(
        request,
        "_jobs_table.html",
        {"jobs": jobs},
        status_code=_STOP_POLLING_STATUS if stop else 200,
    )


@router.get("/jobs/{job_id}/view", response_class=HTMLResponse)
async def job_detail(job_id: str, request: Request) -> HTMLResponse:
    """Render one job's detail page (result/error + metadata), or a 404 page.

    A read-only `GET`, so no Origin check (that guards state-changing POSTs only).
    An unknown/evicted id renders the template's not-found state with HTTP 404 rather
    than JSON, since this is a browser-facing page. The result dict is pretty-printed
    here and rendered inside an autoescaped `<pre>` — untrusted scraped content stays
    inert (no `| safe`).
    """
    job = await request.app.state.job_store.get(job_id)
    if job is None:
        return _templates(request).TemplateResponse(
            request, "job_detail.html", {"job": None}, status_code=404
        )
    result_json = (
        json.dumps(job.result, indent=2, ensure_ascii=False)
        if job.result is not None
        else None
    )
    return _templates(request).TemplateResponse(
        request, "job_detail.html", {"job": job, "result_json": result_json}
    )


@router.get("/jobs/{job_id}/export")
async def export_job(
    job_id: str, request: Request, format: Literal["json", "csv"] = "json"
) -> Response:
    """Download a finished job's result as a JSON or CSV file, generated on the fly.

    A read-only `GET`, so no Origin check. An unknown/evicted id → 404; a job that
    exists but has no result yet (queued/running/error) → 409. The result is returned
    as an attachment; CSV cells that look like spreadsheet formulas are neutralized
    (see `app/dashboard/export.py`). Nothing is persisted.
    """
    job = await request.app.state.job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.result is None:
        raise HTTPException(status_code=409, detail="job has no result to export")
    media_type, serialize = _EXPORTERS[format]
    return Response(
        content=serialize(job.result),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="job-{job_id}.{format}"'
        },
    )


@router.post(
    "/submit",
    response_class=HTMLResponse,
    dependencies=[Depends(require_trusted_origin)],
)
async def submit(
    request: Request,
    url: str = Form(...),
    prompt: str = Form(...),
    output_schema: str = Form(""),
    provider: str = Form(""),
    render: bool = Form(False),
) -> HTMLResponse:
    """Accept the form, enqueue a job, and return a fragment that re-arms polling.

    Bad input (malformed/out-of-subset schema, invalid URL/prompt) and load-shedding
    (at capacity / shutting down) render an inline error fragment with HTTP 200 — HTMX
    does not swap non-2xx responses by default, so the message would otherwise never
    show. No job is created on any of those paths.
    """
    templates = _templates(request)
    try:
        schema = json.loads(output_schema) if output_schema.strip() else None
        req = ExtractRequest(
            url=url,
            prompt=prompt,
            output_schema=schema,
            provider=provider or None,
            render=render,
        )
    except (json.JSONDecodeError, ValidationError) as exc:
        return templates.TemplateResponse(
            request,
            "_submit_result.html",
            {"ok": False, "message": _readable_input_error(exc)},
        )

    try:
        job = await enqueue(
            req,
            scheduler=request.app.state.scheduler,
            store=request.app.state.job_store,
        )
    except AtCapacityError:
        return templates.TemplateResponse(
            request, "_submit_result.html", {"ok": False, "message": _BUSY_MESSAGE}
        )
    except SchedulerShuttingDown:
        return templates.TemplateResponse(
            request, "_submit_result.html", {"ok": False, "message": _SHUTDOWN_MESSAGE}
        )
    return templates.TemplateResponse(
        request, "_submit_result.html", {"ok": True, "job_id": job.id}
    )

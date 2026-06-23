"""Server-rendered dashboard: the shell, the submit form, and its POST handler.

`GET /` renders the form + the live-jobs polling container (F18 fills the container).
`POST /submit` is form-encoded (not the JSON `/extract` route): it builds the same
`ExtractRequest` the API uses, admits it through the shared `enqueue` helper, and
returns an HTML fragment — a success note that re-arms polling (out-of-band swap of
`#jobs`), or an inline error. No scraping/cleaning/LLM logic lives here.
"""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.api.security import require_trusted_origin
from app.jobs.scheduler import SchedulerShuttingDown
from app.jobs.submission import AtCapacityError, enqueue
from app.models import ExtractRequest

router = APIRouter(tags=["dashboard"])

_BUSY_MESSAGE = "Server is at capacity — please retry in a few seconds."
_SHUTDOWN_MESSAGE = "Server is shutting down — please retry shortly."


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

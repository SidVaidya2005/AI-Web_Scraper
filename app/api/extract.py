"""Extraction submission and job-polling endpoints.

`POST /extract` accepts a job and hands it to the bounded scheduler; `GET /jobs` and
`GET /jobs/{job_id}` read job state back. Handlers stay thin: validate the request
(Pydantic, incl. the `output_schema` subset gate), reserve admission, create + submit
the job, and shape a `JobResponse` — no scraping/cleaning/LLM logic lives here.

Admission is reserved *atomically* before the job is created: `try_reserve()` is a
synchronous check-and-increment, so a `has_capacity()` + `await create()` + `submit()`
sequence (a TOCTOU race that overshoots the cap) is never used. The reserved slot is
released on a failed create, a failed submit, or — via the scheduler task's `finally` —
when the job reaches a terminal state.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.security import require_trusted_origin
from app.jobs.scheduler import SchedulerShuttingDown
from app.jobs.submission import AtCapacityError, enqueue
from app.models import ExtractRequest, JobResponse

router = APIRouter(tags=["extract"])

# How long a backpressured client should wait before retrying (Retry-After seconds).
_RETRY_AFTER_SECONDS = 5


@router.post(
    "/extract",
    status_code=202,
    response_model=JobResponse,
    dependencies=[Depends(require_trusted_origin)],
)
async def submit_extraction(req: ExtractRequest, request: Request) -> JobResponse:
    """Accept an extraction job (202 + queued `JobResponse`) or shed load.

    At capacity (`try_reserve()` False) → 429 + `Retry-After`, no job created. The
    rare shutdown race (`submit()` while draining) → 503, with the just-created job
    terminalized so it can't linger `queued`. The admission sequence itself lives in
    the shared `enqueue` helper (also used by the dashboard form POST).
    """
    try:
        job = await enqueue(
            req,
            scheduler=request.app.state.scheduler,
            store=request.app.state.job_store,
        )
    except AtCapacityError:
        raise HTTPException(
            status_code=429,
            detail="server at capacity, retry shortly",
            headers={"Retry-After": str(_RETRY_AFTER_SECONDS)},
        ) from None
    except SchedulerShuttingDown:
        raise HTTPException(
            status_code=503, detail="server shutting down, retry shortly"
        ) from None
    return JobResponse.from_job(job)


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(request: Request) -> list[JobResponse]:
    """List current-session jobs, newest-first (in-memory only; no persistence)."""
    store = request.app.state.job_store
    return [JobResponse.from_job(job) for job in await store.list()]


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, request: Request) -> JobResponse:
    """Return one job's state, or 404 if it is unknown or has been evicted."""
    store = request.app.state.job_store
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobResponse.from_job(job)

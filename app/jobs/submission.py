"""Shared job-admission helper: the one home for reserve -> create -> submit.

Both `POST /extract` (F16) and the dashboard form POST (F17) admit a job the same
way, and the sequence is safety-critical (an `await` in the wrong place is a TOCTOU
race; a missed `release()` leaks a slot). Keeping it here means it cannot drift
between the two call sites — each caller only maps the raised errors to its own
medium (JSON status codes vs an inline HTML fragment).
"""

import logging

from app.jobs.models import Job
from app.jobs.scheduler import SchedulerShuttingDown
from app.jobs.store import JobStore
from app.models import ExtractRequest

logger = logging.getLogger("app.jobs")

_SHUTDOWN_ERROR = "server shutting down"


class AtCapacityError(RuntimeError):
    """The admission cap is full — the caller should shed load (no job was created)."""


async def enqueue(request: ExtractRequest, *, scheduler, store: JobStore) -> Job:
    """Atomically admit `request` as a job and schedule it; return the created `Job`.

    Reserves a slot first (synchronous, atomic), then creates and submits the job.
    Raises `AtCapacityError` when the admission gate is closed (no job created), or
    re-raises `SchedulerShuttingDown` if submission loses the shutdown race — in which
    case the slot is released and the just-created job is terminalized so it can never
    linger `queued`.
    """
    # ATOMIC admission: a sync check-and-increment with no await before submit().
    if not scheduler.try_reserve():
        raise AtCapacityError("server at capacity")
    try:
        job = await store.create(request)
    except BaseException:  # roll the reservation back on any create failure
        scheduler.release()
        raise
    try:
        scheduler.submit(job.id)  # consumes the reservation; concurrency-capped run_job
    except SchedulerShuttingDown:  # only rejects while draining at shutdown
        scheduler.release()
        await store.mark_error(job.id, error=_SHUTDOWN_ERROR)
        logger.warning("rejected job %s: scheduler shutting down", job.id)
        raise
    return job

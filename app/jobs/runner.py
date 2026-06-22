"""Async job runner: drive one job through the pipeline; the error boundary.

`run_job` takes a `queued` job to a terminal state (fetch -> clean -> extract),
recording the result or a readable error via the `JobStore`. It is the project's
top-level error boundary: every failure becomes a recorded job error and nothing
escapes the coroutine, so one job can never crash the scheduler or its siblings.
"""

import logging
from typing import Protocol

from jsonschema.exceptions import ValidationError

from app.cleaning import cleaner
from app.config import Settings
from app.extraction import engine
from app.fetching import browser, fetch_service
from app.fetching.errors import FetchError
from app.jobs.store import JobStateError, JobStore
from app.providers import registry
from app.providers.base import ProviderError

logger = logging.getLogger("app.jobs")


class RunnerState(Protocol):
    """Process-lifetime dependencies `run_job` reads off `app.state`."""

    job_store: JobStore
    browser_manager: browser.BrowserManager
    settings: Settings


async def run_job(job_id: str, *, app_state: RunnerState) -> None:
    """Run one job to a terminal state; never raises (the error boundary).

    Drives `mark_running -> fetch -> clean -> extract -> mark_done`. Known, user-safe
    failures are recorded with their message; any other exception is logged in full
    and recorded as a generic message. Terminalization is best-effort, so an already
    terminal/evicted job cannot make this coroutine raise.
    """
    store = app_state.job_store
    try:
        job = await store.mark_running(job_id)
        fetched = await fetch_service.fetch(
            str(job.request.url),
            browser_manager=app_state.browser_manager,
            settings=app_state.settings,
            render=job.request.render,
        )
        content = cleaner.clean(fetched.html, settings=app_state.settings)
        provider = registry.get_provider(
            app_state.settings, override=job.request.provider
        )
        result = await engine.extract(
            content,
            prompt=job.request.prompt,
            schema=job.request.output_schema,
            provider=provider,
        )
        await store.mark_done(job_id, result=result, mode=fetched.mode)
    except (ProviderError, FetchError, ValidationError) as exc:
        # Known, user-safe failures: their message is written for humans.
        logger.warning("job %s failed: %s", job_id, exc)
        await _terminalize(store, job_id, str(exc))
    except Exception:
        # The boundary: nothing escapes. Keep internals out of the job error.
        logger.exception("job %s failed (internal)", job_id)
        await _terminalize(store, job_id, "internal error — see server logs")


async def _terminalize(store: JobStore, job_id: str, error: str) -> None:
    """Best-effort `mark_error` so `run_job` can't raise if the job is gone/terminal."""
    try:
        await store.mark_error(job_id, error=error)
    except JobStateError:
        logger.warning("job %s already terminal/evicted; error not recorded", job_id)

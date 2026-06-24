"""Async job runner: drive one job through the pipeline; the error boundary.

`run_job` takes a `queued` job to a terminal state (fetch -> clean -> extract),
recording the result or a readable error via the `JobStore`. It is the project's
top-level error boundary: every failure becomes a recorded job error and nothing
escapes the coroutine, so one job can never crash the scheduler or its siblings.
"""

import logging
import time
from typing import Protocol

from jsonschema.exceptions import ValidationError

from app.cleaning import cleaner
from app.config import Settings
from app.extraction import engine
from app.fetching import browser, fetch_service
from app.fetching.errors import FetchError
from app.fetching.respect import RespectfulClient
from app.jobs.store import JobStateError, JobStore
from app.providers import registry
from app.providers.base import ProviderError

logger = logging.getLogger("app.jobs")


class RunnerState(Protocol):
    """Process-lifetime dependencies `run_job` reads off `app.state`."""

    job_store: JobStore
    browser_manager: browser.BrowserManager
    respectful_client: RespectfulClient
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
        started = time.perf_counter()  # total covers the work, not the queued wait
        url = str(job.request.url)
        logger.info("job %s running url=%s render=%s", job_id, url, job.request.render)
        # Be a polite client: enforce per-host rate limit + robots.txt before any
        # fetch. Rejections are FetchError subclasses → recorded by the arm below.
        await app_state.respectful_client.guard(url)
        fetch_start = time.perf_counter()
        fetched = await fetch_service.fetch(
            url,
            browser_manager=app_state.browser_manager,
            settings=app_state.settings,
            render=job.request.render,
        )
        fetch_ms = round((time.perf_counter() - fetch_start) * 1000)
        logger.info(
            "job %s fetched mode=%s fetch_ms=%d", job_id, fetched.mode, fetch_ms
        )
        cleaned = cleaner.clean(fetched.html, settings=app_state.settings)
        if cleaned.truncated:
            logger.warning(
                "job %s content truncated at %d chars; result may be incomplete",
                job_id,
                app_state.settings.max_content_chars,
            )
        provider = registry.get_provider(
            app_state.settings, override=job.request.provider
        )
        extract_start = time.perf_counter()
        result = await engine.extract(
            cleaned.text,
            prompt=job.request.prompt,
            schema=job.request.output_schema,
            provider=provider,
        )
        extract_ms = round((time.perf_counter() - extract_start) * 1000)
        total_ms = round((time.perf_counter() - started) * 1000)
        await store.mark_done(
            job_id,
            result=result,
            mode=fetched.mode,
            fetch_ms=fetch_ms,
            extract_ms=extract_ms,
            total_ms=total_ms,
            content_truncated=cleaned.truncated,
        )
        logger.info(
            "job %s done fetch_ms=%d extract_ms=%d total_ms=%d truncated=%s",
            job_id,
            fetch_ms,
            extract_ms,
            total_ms,
            cleaned.truncated,
        )
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

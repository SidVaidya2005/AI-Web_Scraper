"""Bounded job scheduler: admission control, concurrency cap, graceful drain.

The only sanctioned way to launch background jobs. Two independent bounds protect
memory and the event loop:

* **Concurrency** — `run_job` runs under a `MAX_CONCURRENT_JOBS` semaphore, and every
  task is retained (never a fire-and-forget `create_task`, which can be GC'd
  mid-flight).
* **Admission** — `try_reserve()` is a *synchronous* check-and-increment (no `await`
  between the check and the increment, so it can't interleave on the event loop)
  capping in-flight + waiting jobs at `MAX_QUEUED_JOBS`. A semaphore alone is
  unbounded: waiting tasks and their `queued` jobs would accumulate without limit.

The API handler (F16) reserves a slot, creates the job, then submits it; the slot is
released on terminal state (the task's `finally`), a failed create, or a failed
submit. Admission closes first on shutdown (`try_reserve` -> False), so `submit`'s
only realistic failure is `SchedulerShuttingDown`.
"""

import asyncio
import logging

from app.config import Settings
from app.jobs import runner
from app.jobs.runner import RunnerState
from app.jobs.store import JobStateError

logger = logging.getLogger("app.jobs")

_SHUTDOWN_ERROR = "server shutting down"


class SchedulerShuttingDown(RuntimeError):
    """Raised by `submit()` once the scheduler has begun draining at shutdown."""


class Scheduler:
    """Bounds background job execution by concurrency and atomic admission."""

    def __init__(self, *, app_state: RunnerState, settings: Settings) -> None:
        self._app_state = app_state
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
        self._reserved = 0
        self._draining = False
        self._tasks: set[asyncio.Task[None]] = set()

    def try_reserve(self) -> bool:
        """Atomically admit one job if under the cap and not draining (sync; no await).

        Caps in-flight + waiting jobs at `MAX_QUEUED_JOBS`. Synchronous by design: no
        `await` separates the check from the increment, so two concurrent callers can
        never both pass (a `has_capacity()` + `await create()` + `submit()` sequence
        would be a TOCTOU race that overshoots the cap).
        """
        if self._draining:
            return False
        if self._reserved >= self._settings.max_queued_jobs:
            return False
        self._reserved += 1
        return True

    def release(self) -> None:
        """Release a reserved slot (terminal state / failed create / failed submit)."""
        if self._reserved > 0:
            self._reserved -= 1

    def submit(self, job_id: str) -> None:
        """Schedule `run_job` for an already-reserved job under the concurrency cap.

        Synchronous: creates and retains the task (a strong ref prevents GC of an
        in-flight task). Raises `SchedulerShuttingDown` only while draining — the
        caller then releases the slot and terminalizes the just-created job.
        """
        if self._draining:
            raise SchedulerShuttingDown(_SHUTDOWN_ERROR)
        task = asyncio.create_task(self._run(job_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def shutdown(self) -> None:
        """Stop intake, drain within grace, cancel stragglers, mark survivors error.

        Closes admission first, waits up to `SHUTDOWN_GRACE_SECONDS` for in-flight
        tasks, cancels any that remain, then marks every still non-terminal job
        `error` — runs BEFORE the browser closes so a live render can't outlast it.
        """
        self._draining = True
        if self._tasks:
            pending: set[asyncio.Task[None]]
            _, pending = await asyncio.wait(
                set(self._tasks), timeout=self._settings.shutdown_grace_seconds
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        await self._terminalize_survivors()

    async def _run(self, job_id: str) -> None:
        """Run one job under the semaphore; always release its admission slot."""
        try:
            async with self._semaphore:
                await runner.run_job(job_id, app_state=self._app_state)
        finally:
            self.release()

    async def _terminalize_survivors(self) -> None:
        """`mark_error` every still non-terminal job (best-effort; swallow races)."""
        store = self._app_state.job_store
        for job in await store.list():
            if job.is_terminal:
                continue
            try:
                await store.mark_error(job.id, error=_SHUTDOWN_ERROR)
            except JobStateError:
                logger.warning("job %s already terminal during shutdown", job.id)

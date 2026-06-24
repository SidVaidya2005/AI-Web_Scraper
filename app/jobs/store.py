"""In-memory job registry: the single source of job state for the process.

A `dict[str, Job]` guarded by an `asyncio.Lock`. Terminal jobs are evicted lazily
(swept on `create`/`list`) by TTL — measured from `finished_at` — and by a soft
`MAX_JOBS` cap that drops the oldest terminal jobs; `queued`/`running` jobs are
**never** evicted. No persistence: all state is lost on restart. One instance per
process, created at startup and injected via `app.state`.

State transitions go only through `mark_running`/`mark_done`/`mark_error`, which
enforce the legal lifecycle (`queued → running → done|error`, plus `queued → error`
at shutdown) and protect the "terminal states never change" invariant.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from app.config import Settings
from app.jobs.models import Job, JobStatus
from app.models import ExtractRequest

_TERMINAL = (JobStatus.done, JobStatus.error)


class JobStateError(RuntimeError):
    """An illegal job transition (missing id, or mutating an already-terminal job)."""


class JobStore:
    """In-memory `dict`-backed registry of jobs, guarded by an `asyncio.Lock`."""

    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def create(self, request: ExtractRequest) -> Job:
        """Create and store a `queued` job for `request` (sweeps stale jobs first)."""
        async with self._lock:
            self._evict()
            job = Job(
                id=str(uuid.uuid4()),
                status=JobStatus.queued,
                request=request,
                created_at=datetime.now(tz=UTC),
            )
            self._jobs[job.id] = job
            return job

    async def get(self, job_id: str) -> Job | None:
        """Return the job for `job_id`, or `None` if unknown/evicted."""
        async with self._lock:
            return self._jobs.get(job_id)

    async def list(self) -> list[Job]:
        """Return live jobs newest-first by creation (sweeps evictable jobs first)."""
        async with self._lock:
            self._evict()
            return list(reversed(self._jobs.values()))

    async def mark_running(self, job_id: str) -> Job:
        """Transition `queued → running` and stamp `started_at`."""
        async with self._lock:
            job = self._require(job_id)
            if job.status != JobStatus.queued:
                raise JobStateError(
                    f"job {job_id} cannot start from status {job.status.value}"
                )
            job.status = JobStatus.running
            job.started_at = datetime.now(tz=UTC)
            return job

    async def mark_done(
        self,
        job_id: str,
        *,
        result: dict,
        mode: str,
        fetch_ms: int | None = None,
        extract_ms: int | None = None,
        total_ms: int | None = None,
        content_truncated: bool | None = None,
    ) -> Job:
        """Transition a non-terminal job to `done` with result, mode, and metrics."""
        async with self._lock:
            job = self._require(job_id)
            self._ensure_non_terminal(job)
            job.status = JobStatus.done
            job.result = result
            job.mode = mode
            job.fetch_ms = fetch_ms
            job.extract_ms = extract_ms
            job.total_ms = total_ms
            job.content_truncated = content_truncated
            job.finished_at = datetime.now(tz=UTC)
            return job

    async def mark_error(self, job_id: str, *, error: str) -> Job:
        """Transition a non-terminal job to `error` with a readable message."""
        async with self._lock:
            job = self._require(job_id)
            self._ensure_non_terminal(job)
            job.status = JobStatus.error
            job.error = error
            job.finished_at = datetime.now(tz=UTC)
            return job

    # --- internals (callers must hold `self._lock`) ---

    def _require(self, job_id: str) -> Job:
        """Return the job for `job_id` or raise `JobStateError` if it is gone."""
        job = self._jobs.get(job_id)
        if job is None:
            raise JobStateError(f"job {job_id} not found")
        return job

    @staticmethod
    def _ensure_non_terminal(job: Job) -> None:
        """Raise `JobStateError` if `job` is already terminal (terminal is final)."""
        if job.is_terminal:
            raise JobStateError(
                f"job {job.id} is already terminal ({job.status.value})"
            )

    def _evict(self) -> None:
        """Drop expired and excess **terminal** jobs; never touch `queued`/`running`."""
        now = datetime.now(tz=UTC)
        ttl = self._settings.job_ttl_seconds
        expired = [
            jid
            for jid, job in self._jobs.items()
            if job.is_terminal
            and job.finished_at is not None
            and (now - job.finished_at).total_seconds() > ttl
        ]
        for jid in expired:
            del self._jobs[jid]

        # Soft cap: drop oldest terminal jobs (insertion order == creation order)
        # until within MAX_JOBS. Non-terminal jobs are immune, so the store may
        # exceed the cap if the overflow is all queued/running.
        if len(self._jobs) > self._settings.max_jobs:
            for jid, job in list(self._jobs.items()):
                if len(self._jobs) <= self._settings.max_jobs:
                    break
                if job.is_terminal:
                    del self._jobs[jid]

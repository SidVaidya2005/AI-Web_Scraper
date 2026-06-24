"""The in-memory unit of job state: the `Job` record and its `JobStatus` lifecycle.

A `Job` is created `queued`, moves to `running` when the worker starts, and ends
terminal (`done` or `error`). It holds the original request plus the fetch mode,
result/error, and lifecycle timestamps. State lives only in memory (no database);
the `JobStore` (app/jobs/store.py) is the single source of truth and the only place
these records are mutated.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.models import ExtractRequest


class JobStatus(StrEnum):
    """The lifecycle states of a job; `done`/`error` are terminal and never change."""

    queued = "queued"
    running = "running"
    done = "done"
    error = "error"


class Job(BaseModel):
    """A single extraction job's full state, held in memory for the process lifetime."""

    id: str
    status: JobStatus
    request: ExtractRequest
    mode: str | None = None  # "http" | "browser"; None until fetched
    result: dict | None = None  # structured output (object envelope); set on done
    error: str | None = None  # readable failure message; set on error
    created_at: datetime
    started_at: datetime | None = None  # set when the worker begins (running)
    finished_at: datetime | None = None  # set on a terminal state; TTL measured from it
    # Per-job metrics, recorded on `done` (rounded ms); None until then.
    fetch_ms: int | None = None  # fetch_service call (incl. render when mode=browser)
    extract_ms: int | None = None  # the LLM extraction call
    total_ms: int | None = None  # whole pipeline: guard -> fetch -> clean -> extract
    content_truncated: bool | None = None  # cleaned text hit the char cap (lossy)

    @property
    def is_terminal(self) -> bool:
        """True when the job is in a terminal state (`done` or `error`)."""
        return self.status in (JobStatus.done, JobStatus.error)

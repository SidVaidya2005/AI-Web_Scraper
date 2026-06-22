"""Shared API-facing Pydantic models.

`ExtractRequest` is the wire contract for `POST /extract` and the dashboard form;
`JobResponse` is the read model returned by `GET /jobs` and `GET /jobs/{id}` (F16).

`JobResponse` reads a `Job` only via `from_job()` and is typed to need **no runtime
import** from `app/jobs` (the `Job` annotation is `TYPE_CHECKING`-only and `status`
is a plain `str`). That severs an otherwise-circular import, since `app/jobs/models`
imports `ExtractRequest` from here for its `Job.request` field.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.extraction.schemas import validate_request_schema

if TYPE_CHECKING:
    from app.jobs.models import Job


class ExtractRequest(BaseModel):
    """A single extraction submission: where to fetch, what to extract, and how.

    A supplied `output_schema` is validated against the supported JSON-Schema
    subset here, so a malformed/out-of-subset schema is rejected at the boundary
    (Pydantic `ValidationError` → FastAPI 422).
    """

    url: HttpUrl
    prompt: str = Field(min_length=1)
    output_schema: dict | None = None  # optional JSON Schema document for typed output
    provider: str | None = None  # optional per-request provider override
    render: bool = False  # opt in to headless-browser rendering (local-network risk)

    @field_validator("output_schema")
    @classmethod
    def _validate_output_schema(cls, value: dict | None) -> dict | None:
        """Reject an unsupported `output_schema` at construction (raises ValueError)."""
        if value is not None:
            validate_request_schema(value)
        return value


class JobResponse(BaseModel):
    """API view of a job's state, returned by the extract/jobs endpoints (F16).

    `status` is a plain string (the `JobStatus` value) so this module needs no
    runtime import from `app/jobs` — see the module docstring on the import cycle.
    """

    job_id: str
    status: str
    url: str  # echoed from the request so a polling client sees which job it is
    prompt: str
    mode: str | None
    result: dict | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_job(cls, job: "Job") -> "JobResponse":
        """Build the response view from a stored `Job`."""
        return cls(
            job_id=job.id,
            status=job.status.value,
            url=str(job.request.url),
            prompt=job.request.prompt,
            mode=job.mode,
            result=job.result,
            error=job.error,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )

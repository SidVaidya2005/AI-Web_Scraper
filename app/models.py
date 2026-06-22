"""Shared API-facing Pydantic models.

`ExtractRequest` is the wire contract for `POST /extract` and the dashboard form.
`JobResponse` is intentionally absent until F13/F16 — it depends on the `Job` /
`JobStatus` types that land with the job store in Feature 13.
"""

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.extraction.schemas import validate_request_schema


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

"""Tests for app.models (F11/F13): the ExtractRequest wire contract and JobResponse.

The `output_schema` field-validator wires the F11 subset gate, so a bad schema
surfaces as a Pydantic ValidationError — which FastAPI renders as 422 in F16.
`JobResponse.from_job` (F13) maps a stored Job into the API read model.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.jobs.models import Job, JobStatus
from app.models import ExtractRequest, JobResponse


def test_valid_request_builds_with_defaults() -> None:
    req = ExtractRequest(url="https://example.com/products", prompt="get titles")
    assert req.prompt == "get titles"
    assert req.render is False
    assert req.output_schema is None
    assert req.provider is None


def test_bad_url_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractRequest(url="not-a-url", prompt="x")


def test_empty_prompt_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractRequest(url="https://example.com", prompt="")


def test_valid_output_schema_accepted() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "string"}}}
    req = ExtractRequest(
        url="https://example.com", prompt="x", output_schema=schema, render=True
    )
    assert req.output_schema == schema
    assert req.render is True


def test_root_non_object_output_schema_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractRequest(
            url="https://example.com",
            prompt="x",
            output_schema={"type": "array", "items": {"type": "string"}},
        )


def test_out_of_subset_output_schema_rejected() -> None:
    with pytest.raises(ValidationError):
        ExtractRequest(
            url="https://example.com",
            prompt="x",
            output_schema={"type": "object", "not": {"type": "string"}},
        )


def test_jobresponse_from_job_maps_fields() -> None:
    now = datetime.now(tz=UTC)
    req = ExtractRequest(url="https://example.com/products", prompt="get titles")
    job = Job(
        id="abc",
        status=JobStatus.done,
        request=req,
        mode="http",
        result={"items": [1, 2]},
        created_at=now,
        started_at=now,
        finished_at=now,
    )
    resp = JobResponse.from_job(job)
    assert resp.job_id == "abc"
    assert resp.status == "done"
    assert type(resp.status) is str  # plain string, not the JobStatus enum
    assert resp.url == "https://example.com/products"  # HttpUrl serialized to str
    assert resp.prompt == "get titles"
    assert resp.mode == "http"
    assert resp.result == {"items": [1, 2]}
    assert resp.error is None
    assert resp.created_at == now == resp.started_at == resp.finished_at


def test_jobresponse_carries_error_and_nulls_for_unfinished() -> None:
    now = datetime.now(tz=UTC)
    req = ExtractRequest(url="https://example.com/products", prompt="x")
    job = Job(
        id="e1", status=JobStatus.error, request=req, error="boom", created_at=now
    )
    resp = JobResponse.from_job(job)
    assert resp.status == "error"
    assert resp.error == "boom"
    assert resp.mode is None and resp.result is None
    assert resp.started_at is None and resp.finished_at is None

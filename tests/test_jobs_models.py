"""Tests for app.jobs.models (F13): the Job record and JobStatus lifecycle."""

from datetime import UTC, datetime

from app.jobs.models import Job, JobStatus
from app.models import ExtractRequest


def _req() -> ExtractRequest:
    return ExtractRequest(url="https://example.com/products", prompt="get titles")


def test_jobstatus_values() -> None:
    assert [s.value for s in JobStatus] == ["queued", "running", "done", "error"]


def test_job_defaults_are_unset() -> None:
    job = Job(
        id="abc",
        status=JobStatus.queued,
        request=_req(),
        created_at=datetime.now(tz=UTC),
    )
    assert job.mode is None
    assert job.result is None
    assert job.error is None
    assert job.started_at is None
    assert job.finished_at is None


def test_is_terminal() -> None:
    now = datetime.now(tz=UTC)
    req = _req()

    def job(status: JobStatus) -> Job:
        return Job(id=status.value, status=status, request=req, created_at=now)

    assert job(JobStatus.queued).is_terminal is False
    assert job(JobStatus.running).is_terminal is False
    assert job(JobStatus.done).is_terminal is True
    assert job(JobStatus.error).is_terminal is True

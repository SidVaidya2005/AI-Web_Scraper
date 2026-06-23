"""Tests for the shared admission helper (F17): app/jobs/submission.enqueue.

`enqueue` is the single home for the atomic reserve -> create -> submit sequence
that both `POST /extract` (F16) and the dashboard form POST (F17) call. These tests
drive its real orchestration against a real `JobStore` and a small fake scheduler
that triggers each branch — capacity, create-failure, shutdown — deterministically.
"""

import pytest

from app.config import Settings
from app.jobs.scheduler import SchedulerShuttingDown
from app.jobs.store import JobStore
from app.jobs.submission import AtCapacityError, enqueue
from app.models import ExtractRequest

_REQUEST = ExtractRequest(url="https://example.com/", prompt="get the title")


class _FakeScheduler:
    """Records admission calls and can be configured to refuse or fail a submit."""

    def __init__(
        self, *, reserve: bool = True, submit_exc: Exception | None = None
    ) -> None:
        self._reserve = reserve
        self._submit_exc = submit_exc
        self.reserved = 0
        self.released = 0
        self.submitted: list[str] = []

    def try_reserve(self) -> bool:
        if not self._reserve:
            return False
        self.reserved += 1
        return True

    def release(self) -> None:
        self.released += 1

    def submit(self, job_id: str) -> None:
        if self._submit_exc is not None:
            raise self._submit_exc
        self.submitted.append(job_id)


def _store() -> JobStore:
    return JobStore(settings=Settings(_env_file=None))


async def test_enqueue_creates_submits_and_returns_job() -> None:
    store = _store()
    scheduler = _FakeScheduler()

    job = await enqueue(_REQUEST, scheduler=scheduler, store=store)

    assert scheduler.submitted == [job.id]
    assert scheduler.reserved == 1 and scheduler.released == 0
    listed = await store.list()
    assert [j.id for j in listed] == [job.id]
    assert job.request.render is False


async def test_enqueue_at_capacity_raises_and_creates_no_job() -> None:
    store = _store()
    scheduler = _FakeScheduler(reserve=False)

    with pytest.raises(AtCapacityError):
        await enqueue(_REQUEST, scheduler=scheduler, store=store)

    assert scheduler.submitted == []
    assert await store.list() == []


async def test_enqueue_releases_slot_when_create_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store()
    scheduler = _FakeScheduler()

    async def _boom(_request: ExtractRequest) -> None:
        raise RuntimeError("store create failed")

    monkeypatch.setattr(store, "create", _boom)

    with pytest.raises(RuntimeError, match="store create failed"):
        await enqueue(_REQUEST, scheduler=scheduler, store=store)

    assert scheduler.released == 1  # reservation rolled back
    assert scheduler.submitted == []


async def test_enqueue_on_shutdown_releases_slot_and_terminalizes_job() -> None:
    store = _store()
    scheduler = _FakeScheduler(submit_exc=SchedulerShuttingDown("server shutting down"))

    with pytest.raises(SchedulerShuttingDown):
        await enqueue(_REQUEST, scheduler=scheduler, store=store)

    assert scheduler.released == 1
    listed = await store.list()
    assert len(listed) == 1
    assert listed[0].status.value == "error"
    assert listed[0].error == "server shutting down"

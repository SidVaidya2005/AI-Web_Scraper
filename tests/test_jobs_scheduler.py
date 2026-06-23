"""Tests for app.jobs.scheduler (F15): bounded background execution + drain.

The scheduler runs against a real in-memory JobStore; the job coroutine seam
(`runner.run_job`) is monkeypatched with fakes that record calls, block on an
`asyncio.Event`, or drive the store. Timing is deterministic — jobs are gated with
an Event and `shutdown_grace_seconds=0` forces the straggler/cancel path, so no test
sleeps on the wall clock.

Pinned behaviors: `try_reserve` admits exactly `max_queued_jobs` (atomic, no
overshoot) and `release` frees a slot; draining closes admission (`try_reserve` ->
False, `submit` -> SchedulerShuttingDown); `run_job` runs under the
`MAX_CONCURRENT_JOBS` semaphore with retained task refs; the admission slot is
released on task completion; shutdown drains within grace, cancels stragglers, and
marks every non-terminal survivor `error` before returning.
"""

import asyncio
import types
from typing import Any

import pytest

from app.config import Settings
from app.jobs import runner
from app.jobs.models import JobStatus
from app.jobs.scheduler import Scheduler, SchedulerShuttingDown
from app.jobs.store import JobStore
from app.models import ExtractRequest


def _settings(**overrides: Any) -> Settings:
    overrides.setdefault("anthropic_api_key", "test-key")
    return Settings(_env_file=None, **overrides)


def _app_state(store: JobStore, settings: Settings) -> types.SimpleNamespace:
    # browser_manager is never touched (run_job is faked); a sentinel is enough.
    return types.SimpleNamespace(
        job_store=store, browser_manager=object(), settings=settings
    )


def _scheduler(**overrides: Any) -> tuple[Scheduler, JobStore, Settings]:
    settings = _settings(**overrides)
    store = JobStore(settings=settings)
    sched = Scheduler(app_state=_app_state(store, settings), settings=settings)
    return sched, store, settings


async def _make_job(store: JobStore) -> str:
    job = await store.create(ExtractRequest(url="https://example.com/", prompt="p"))
    return job.id


def test_try_reserve_admits_exactly_max_queued_then_rejects() -> None:
    sched, _, _ = _scheduler(max_concurrent_jobs=1, max_queued_jobs=3, max_jobs=10)
    assert [sched.try_reserve() for _ in range(5)] == [True, True, True, False, False]


def test_release_frees_a_slot_and_underflow_is_safe() -> None:
    sched, _, _ = _scheduler(max_concurrent_jobs=1, max_queued_jobs=1, max_jobs=10)
    sched.release()  # underflow before any reserve is a safe no-op
    assert sched.try_reserve() is True
    assert sched.try_reserve() is False  # at cap
    sched.release()
    assert sched.try_reserve() is True  # freed slot is reusable


async def test_draining_closes_admission_and_submit_raises() -> None:
    sched, _, _ = _scheduler()
    await sched.shutdown()  # begins draining (no tasks)
    assert sched.try_reserve() is False
    with pytest.raises(SchedulerShuttingDown):
        sched.submit("any-id")


async def test_submit_runs_job_and_releases_slot(monkeypatch) -> None:
    sched, store, _ = _scheduler()
    job_id = await _make_job(store)
    ran: list[str] = []

    async def fake_run_job(jid: str, *, app_state) -> None:
        ran.append(jid)

    monkeypatch.setattr(runner, "run_job", fake_run_job)

    assert sched.try_reserve() is True
    sched.submit(job_id)
    await asyncio.gather(*set(sched._tasks))
    await asyncio.sleep(0)  # let the done-callback discard the task

    assert ran == [job_id]
    assert sched._reserved == 0  # slot released in the task's finally
    assert sched._tasks == set()  # task ref dropped after completion


async def test_run_job_runs_under_concurrency_semaphore(monkeypatch) -> None:
    sched, store, _ = _scheduler(max_concurrent_jobs=2, max_queued_jobs=5, max_jobs=10)
    gate = asyncio.Event()
    current = 0
    peak = 0

    async def fake_run_job(jid: str, *, app_state) -> None:
        nonlocal current, peak
        current += 1
        peak = max(peak, current)
        try:
            await gate.wait()
        finally:
            current -= 1

    monkeypatch.setattr(runner, "run_job", fake_run_job)

    for _ in range(4):
        job_id = await _make_job(store)
        assert sched.try_reserve() is True
        sched.submit(job_id)

    for _ in range(20):  # let everything that can run, run
        await asyncio.sleep(0)

    assert current == 2  # only MAX_CONCURRENT_JOBS run at once
    assert peak == 2

    gate.set()
    await asyncio.gather(*set(sched._tasks))
    assert peak == 2  # never exceeded the cap, even across hand-offs
    assert sched._reserved == 0


async def test_shutdown_lets_in_grace_job_finish(monkeypatch) -> None:
    sched, store, _ = _scheduler(shutdown_grace_seconds=5)
    job_id = await _make_job(store)

    async def fake_run_job(jid: str, *, app_state) -> None:
        await app_state.job_store.mark_running(jid)
        await app_state.job_store.mark_done(jid, result={"ok": True}, mode="http")

    monkeypatch.setattr(runner, "run_job", fake_run_job)

    assert sched.try_reserve() is True
    sched.submit(job_id)
    await sched.shutdown()  # job finishes immediately; wait returns before grace

    done = await store.get(job_id)
    assert done is not None
    assert done.status is JobStatus.done
    assert done.result == {"ok": True}


async def test_shutdown_cancels_straggler_and_marks_error(monkeypatch) -> None:
    sched, store, _ = _scheduler(shutdown_grace_seconds=0)
    job_id = await _make_job(store)
    gate = asyncio.Event()  # never set: the job hangs until cancelled

    async def fake_run_job(jid: str, *, app_state) -> None:
        await app_state.job_store.mark_running(jid)
        await gate.wait()

    monkeypatch.setattr(runner, "run_job", fake_run_job)

    assert sched.try_reserve() is True
    sched.submit(job_id)
    for _ in range(10):  # let the task start and mark running
        await asyncio.sleep(0)
        j = await store.get(job_id)
        if j is not None and j.status is JobStatus.running:
            break

    await sched.shutdown()

    final = await store.get(job_id)
    assert final is not None
    assert final.status is JobStatus.error
    assert final.error == "server shutting down"


async def test_shutdown_marks_queued_on_semaphore_job_error(monkeypatch) -> None:
    sched, store, _ = _scheduler(
        max_concurrent_jobs=1, max_queued_jobs=5, max_jobs=10, shutdown_grace_seconds=0
    )
    gate = asyncio.Event()  # never set

    async def fake_run_job(jid: str, *, app_state) -> None:
        await app_state.job_store.mark_running(jid)
        await gate.wait()

    monkeypatch.setattr(runner, "run_job", fake_run_job)

    ids = []
    for _ in range(2):
        job_id = await _make_job(store)
        ids.append(job_id)
        assert sched.try_reserve() is True
        sched.submit(job_id)

    for _ in range(10):  # job 0 acquires the sole sem slot; job 1 waits (still queued)
        await asyncio.sleep(0)

    s0 = await store.get(ids[0])
    s1 = await store.get(ids[1])
    assert s0 is not None and s0.status is JobStatus.running
    assert s1 is not None and s1.status is JobStatus.queued

    await sched.shutdown()

    f0 = await store.get(ids[0])
    f1 = await store.get(ids[1])
    assert f0 is not None and f0.status is JobStatus.error
    assert f1 is not None and f1.status is JobStatus.error  # queued survivor swept too


async def test_shutdown_with_no_tasks_is_safe_and_idempotent() -> None:
    sched, _, _ = _scheduler()
    await sched.shutdown()
    await sched.shutdown()  # second call is a no-op
    assert sched.try_reserve() is False

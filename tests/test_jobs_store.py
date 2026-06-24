"""Tests for app.jobs.store (F13): the in-memory JobStore.

TTL is exercised deterministically by pushing a stored job's `finished_at` into the
past and re-triggering a sweep (via list/create) — no real waiting. Settings are
built with `_env_file=None` so a dev-shell `.env` can't bleed in.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.jobs.models import JobStatus
from app.jobs.store import JobStateError, JobStore
from app.models import ExtractRequest


def _req(prompt: str = "get titles") -> ExtractRequest:
    return ExtractRequest(url="https://example.com/products", prompt=prompt)


def _store(**overrides: object) -> JobStore:
    return JobStore(settings=Settings(_env_file=None, **overrides))


# --- create / get ---


async def test_create_returns_queued_job() -> None:
    store = _store()
    req = _req()
    job = await store.create(req)
    assert job.status is JobStatus.queued
    assert uuid.UUID(job.id)  # a valid uuid4 string
    assert job.created_at.tzinfo is not None  # tz-aware
    assert job.started_at is None and job.finished_at is None
    assert job.request is req


async def test_get_round_trips_and_unknown_is_none() -> None:
    store = _store()
    job = await store.create(_req())
    assert (await store.get(job.id)) is job
    assert (await store.get("nope")) is None


# --- transitions set timestamps ---


async def test_mark_running_sets_status_and_started_at() -> None:
    store = _store()
    job = await store.create(_req())
    running = await store.mark_running(job.id)
    assert running.status is JobStatus.running
    assert running.started_at is not None
    assert running.finished_at is None


async def test_mark_done_sets_result_mode_and_finished_at() -> None:
    store = _store()
    job = await store.create(_req())
    await store.mark_running(job.id)
    done = await store.mark_done(job.id, result={"items": [1]}, mode="http")
    assert done.status is JobStatus.done
    assert done.result == {"items": [1]}
    assert done.mode == "http"
    assert done.finished_at is not None


async def test_mark_done_records_timing_and_truncation_metrics() -> None:
    store = _store()
    job = await store.create(_req())
    await store.mark_running(job.id)
    done = await store.mark_done(
        job.id,
        result={"ok": True},
        mode="browser",
        fetch_ms=120,
        extract_ms=950,
        total_ms=1100,
        content_truncated=True,
    )
    assert done.fetch_ms == 120
    assert done.extract_ms == 950
    assert done.total_ms == 1100
    assert done.content_truncated is True


async def test_mark_done_metrics_default_to_none() -> None:
    store = _store()
    job = await store.create(_req())
    await store.mark_running(job.id)
    done = await store.mark_done(job.id, result={}, mode="http")
    assert done.fetch_ms is None
    assert done.extract_ms is None
    assert done.total_ms is None
    assert done.content_truncated is None


async def test_mark_error_from_running_and_from_queued() -> None:
    store = _store()
    # running → error
    j1 = await store.create(_req())
    await store.mark_running(j1.id)
    err = await store.mark_error(j1.id, error="boom")
    assert err.status is JobStatus.error and err.error == "boom"
    assert err.finished_at is not None
    # queued → error (the shutdown path) is allowed
    j2 = await store.create(_req())
    err2 = await store.mark_error(j2.id, error="server shutting down")
    assert err2.status is JobStatus.error


# --- transition guards ---


async def test_mark_running_on_non_queued_raises() -> None:
    store = _store()
    job = await store.create(_req())
    await store.mark_running(job.id)
    with pytest.raises(JobStateError):
        await store.mark_running(job.id)


async def test_mark_on_terminal_raises() -> None:
    store = _store()
    job = await store.create(_req())
    await store.mark_running(job.id)
    await store.mark_done(job.id, result={}, mode="http")
    with pytest.raises(JobStateError):
        await store.mark_done(job.id, result={}, mode="http")
    with pytest.raises(JobStateError):
        await store.mark_error(job.id, error="late")


async def test_mark_missing_id_raises() -> None:
    store = _store()
    with pytest.raises(JobStateError):
        await store.mark_running("missing")


# --- listing ---


async def test_list_is_newest_first() -> None:
    store = _store()
    a = await store.create(_req("a"))
    b = await store.create(_req("b"))
    c = await store.create(_req("c"))
    assert [j.id for j in await store.list()] == [c.id, b.id, a.id]


# --- eviction ---


async def test_ttl_evicts_terminal_only() -> None:
    store = _store(job_ttl_seconds=1)
    done = await store.create(_req())
    await store.mark_running(done.id)
    await store.mark_done(done.id, result={}, mode="http")
    # age the terminal job past its TTL
    done.finished_at = datetime.now(tz=UTC) - timedelta(seconds=5)

    remaining = await store.list()
    assert done.id not in {j.id for j in remaining}


async def test_ttl_never_evicts_running_or_queued() -> None:
    store = _store(job_ttl_seconds=1)
    running = await store.create(_req("r"))
    await store.mark_running(running.id)
    running.started_at = datetime.now(tz=UTC) - timedelta(
        seconds=100
    )  # old, non-terminal
    queued = await store.create(_req("q"))

    ids = {j.id for j in await store.list()}
    assert running.id in ids and queued.id in ids


async def test_max_jobs_evicts_oldest_terminal() -> None:
    store = _store(max_concurrent_jobs=1, max_queued_jobs=1, max_jobs=2)
    ids = []
    for _ in range(3):
        job = await store.create(_req())
        await store.mark_running(job.id)
        await store.mark_done(job.id, result={}, mode="http")
        ids.append(job.id)

    remaining = {j.id for j in await store.list()}  # list() triggers the sweep
    assert len(remaining) == 2
    assert ids[0] not in remaining  # oldest terminal dropped
    assert ids[1] in remaining and ids[2] in remaining


async def test_max_jobs_keeps_non_terminal_over_cap() -> None:
    store = _store(max_concurrent_jobs=1, max_queued_jobs=1, max_jobs=2)
    for _ in range(3):
        await store.create(_req())  # all left queued (non-terminal)

    remaining = await store.list()
    assert len(remaining) == 3  # nothing evicted — queued jobs are immune


async def test_concurrent_creates_are_all_stored() -> None:
    store = _store()
    jobs = await asyncio.gather(*(store.create(_req()) for _ in range(20)))
    assert len({j.id for j in jobs}) == 20
    assert len(await store.list()) == 20

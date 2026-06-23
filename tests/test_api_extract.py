"""Tests for the extract & jobs API (F16): POST /extract, GET /jobs, GET /jobs/{id}.

The app runs through a real lifespan (real `JobStore` + `Scheduler`); the pipeline
seam (`app.jobs.runner.run_job`) is stubbed with a fake that drives the job straight
to a terminal state, so no test touches the network or an LLM. Each test uses its own
`with TestClient(app)` block, which re-runs startup for a fresh store/scheduler.

`base_url="http://127.0.0.1"` keeps the Host allow-listed (TrustedHostMiddleware);
`Origin` is never sent unless a test sets it explicitly (httpx adds none).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.jobs import runner
from app.jobs.scheduler import SchedulerShuttingDown
from app.main import app

_PAYLOAD = {"url": "https://example.com/", "prompt": "get the title"}


async def _fake_run_job_done(job_id: str, *, app_state) -> None:
    """Stub runner: take the job queued -> running -> done with a fixed result."""
    await app_state.job_store.mark_running(job_id)
    await app_state.job_store.mark_done(job_id, result={"ok": True}, mode="http")


def _stub_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "run_job", _fake_run_job_done)


def _poll_until_terminal(client: TestClient, job_id: str, *, tries: int = 50) -> dict:
    """Poll GET /jobs/{id} until terminal; each GET pumps the background task's loop."""
    for _ in range(tries):
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in ("done", "error"):
            return body
    raise AssertionError(f"job {job_id} never reached a terminal state")


def test_submit_returns_202_queued_then_polls_to_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_runner(monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post("/extract", json=_PAYLOAD)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"
        assert body["url"] == "https://example.com/"
        assert body["prompt"] == "get the title"
        assert body["result"] is None and body["finished_at"] is None
        job_id = body["job_id"]

        final = _poll_until_terminal(client, job_id)
        assert final["status"] == "done"
        assert final["result"] == {"ok": True}
        assert final["mode"] == "http"
        assert final["finished_at"] is not None


def test_list_jobs_is_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_runner(monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        first = client.post("/extract", json=_PAYLOAD).json()["job_id"]
        second = client.post("/extract", json=_PAYLOAD).json()["job_id"]

        listed = client.get("/jobs")
        assert listed.status_code == 200
        ids = [job["job_id"] for job in listed.json()]
        assert ids == [second, first]  # newest-first


def test_get_unknown_job_returns_404() -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.get(f"/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "job not found"


def test_bad_output_schema_returns_422() -> None:
    # Root-non-object schema is rejected by the ExtractRequest field_validator (F11).
    payload = {**_PAYLOAD, "output_schema": {"type": "array"}}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post("/extract", json=payload)
    assert resp.status_code == 422


def test_valid_output_schema_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_runner(monkeypatch)
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post("/extract", json={**_PAYLOAD, "output_schema": schema})
    assert resp.status_code == 202


def test_at_capacity_returns_429_and_creates_no_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        # Force the admission gate closed without depending on the configured cap value.
        monkeypatch.setattr(app.state.scheduler, "try_reserve", lambda: False)
        resp = client.post("/extract", json=_PAYLOAD)
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "5"
        # No job was created (reservation failed before create()).
        assert client.get("/jobs").json() == []


def test_shutdown_race_returns_503_and_terminalizes_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        scheduler = app.state.scheduler

        def boom(job_id: str) -> None:
            raise SchedulerShuttingDown("server shutting down")

        monkeypatch.setattr(scheduler, "submit", boom)
        resp = client.post("/extract", json=_PAYLOAD)
        assert resp.status_code == 503

        jobs = client.get("/jobs").json()
        assert len(jobs) == 1
        assert jobs[0]["status"] == "error"
        assert jobs[0]["error"] == "server shutting down"
        # Reserved slot was released on the failed submit (no leak).
        assert scheduler._reserved == 0


def test_origin_allowed_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_runner(monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post(
            "/extract", json=_PAYLOAD, headers={"Origin": "http://127.0.0.1"}
        )
    assert resp.status_code == 202


def test_origin_disallowed_is_rejected_and_creates_no_job() -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post(
            "/extract", json=_PAYLOAD, headers={"Origin": "http://evil.com"}
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "cross-origin request rejected"
        assert client.get("/jobs").json() == []  # rejected before any job was created


def test_missing_origin_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    # Non-browser clients (curl/httpx) send no Origin — the lenient guard allows it.
    _stub_runner(monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post("/extract", json=_PAYLOAD)
    assert resp.status_code == 202

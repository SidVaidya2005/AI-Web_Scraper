"""Tests for the dashboard (F17): GET / shell + the form-handling POST /submit.

The app runs a real lifespan (real `JobStore`/`Scheduler`); the pipeline seam
(`app.jobs.runner.run_job`) is stubbed so a submitted job terminates without touching
the network or an LLM. `base_url="http://127.0.0.1"` keeps the Host allow-listed; the
form POST is `application/x-www-form-urlencoded` (`client.post(data=...)`).
"""

import csv
import io
import json
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.dashboard import routes
from app.jobs import runner, submission
from app.jobs.models import Job, JobStatus
from app.main import app
from app.models import ExtractRequest

_FORM = {"url": "https://example.com/", "prompt": "get the title"}


async def _fake_run_job_done(job_id: str, *, app_state) -> None:
    await app_state.job_store.mark_running(job_id)
    await app_state.job_store.mark_done(job_id, result={"ok": True}, mode="http")


def _stub_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "run_job", _fake_run_job_done)


def _spy_enqueue(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Wrap the real enqueue so a test can inspect the ExtractRequest it built."""
    captured: dict = {}
    real = submission.enqueue

    async def _spy(request, **kwargs):
        captured["request"] = request
        return await real(request, **kwargs)

    monkeypatch.setattr(routes, "enqueue", _spy)
    return captured


def test_get_index_renders_form_and_polling_container() -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert 'hx-post="/submit"' in body
    assert 'name="url"' in body and 'name="prompt"' in body
    # render checkbox present and NOT pre-checked, with its risk note.
    assert 'type="checkbox"' in body and 'name="render"' in body
    assert "checked" not in body
    assert "local network" in body.lower() or "ip-pinning" in body.lower()
    # submit-result slot + the polling container with the every-2s trigger.
    assert 'id="submit-result"' in body
    assert 'id="jobs"' in body
    assert "every 2s" in body


def test_submit_creates_job_and_rearms_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_runner(monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post("/submit", data=_FORM)
        assert resp.status_code == 200
        body = resp.text
        assert "Job queued" in body
        # Re-arms a (possibly stopped) poller via an OOB swap of #jobs.
        assert 'hx-swap-oob="true"' in body
        assert "every 2s" in body
        # The job really exists.
        jobs = client.get("/jobs").json()
        assert len(jobs) == 1
        assert jobs[0]["url"] == "https://example.com/"


def test_submit_render_unchecked_defaults_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_runner(monkeypatch)
    captured = _spy_enqueue(monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post("/submit", data=_FORM)  # no render field
    assert resp.status_code == 200
    assert captured["request"].render is False


def test_submit_render_checkbox_enables_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_runner(monkeypatch)
    captured = _spy_enqueue(monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post("/submit", data={**_FORM, "render": "true"})
    assert resp.status_code == 200
    assert captured["request"].render is True


def test_submit_valid_output_schema_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_runner(monkeypatch)
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post(
            "/submit", data={**_FORM, "output_schema": json.dumps(schema)}
        )
        assert resp.status_code == 200
        assert "Job queued" in resp.text
        assert len(client.get("/jobs").json()) == 1


def test_submit_malformed_json_schema_shows_error_and_no_job() -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post("/submit", data={**_FORM, "output_schema": "{not json"})
        assert resp.status_code == 200
        assert "Job queued" not in resp.text
        assert "JSON" in resp.text  # readable error
        assert client.get("/jobs").json() == []


def test_submit_out_of_subset_schema_shows_error_and_no_job() -> None:
    # Root-non-object schema is rejected by ExtractRequest's field_validator (F11).
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post(
            "/submit", data={**_FORM, "output_schema": json.dumps({"type": "array"})}
        )
        assert resp.status_code == 200
        assert "Job queued" not in resp.text
        assert client.get("/jobs").json() == []


def test_submit_invalid_url_shows_error_and_no_job() -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post("/submit", data={**_FORM, "url": "not-a-url"})
        assert resp.status_code == 200
        assert "Job queued" not in resp.text
        assert client.get("/jobs").json() == []


def test_submit_disallowed_origin_rejected_and_no_job() -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.post("/submit", data=_FORM, headers={"Origin": "http://evil.com"})
        assert resp.status_code == 403
        assert client.get("/jobs").json() == []


def test_submit_at_capacity_shows_busy_and_no_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        monkeypatch.setattr(app.state.scheduler, "try_reserve", lambda: False)
        resp = client.post("/submit", data=_FORM)
        assert resp.status_code == 200
        assert "Job queued" not in resp.text
        assert "capacity" in resp.text.lower()
        assert client.get("/jobs").json() == []


# --- F18: GET /partials/jobs (live jobs table + 286 stop-polling) ---

_STAMP = datetime(2026, 6, 23, 14, 2, 11, tzinfo=UTC)


def _job(
    status: JobStatus,
    *,
    mode: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> Job:
    """Build a Job with a valid request and chosen status/timestamps for the table."""
    return Job(
        id=str(uuid.uuid4()),
        status=status,
        request=ExtractRequest(url="https://example.com/", prompt="x"),
        mode=mode,
        created_at=_STAMP,
        started_at=_STAMP if started else None,
        finished_at=_STAMP if finished else None,
    )


def _patch_list(monkeypatch: pytest.MonkeyPatch, jobs: list[Job]) -> None:
    """Make the live store's `list()` return `jobs` (deterministic, no scheduler).

    Safe even for non-terminal `jobs`: at shutdown `_terminalize_survivors` calls
    `mark_error` on ids absent from the real store, which raises a swallowed
    `JobStateError`.
    """

    async def _list() -> list[Job]:
        return jobs

    monkeypatch.setattr(app.state.job_store, "list", _list)


def test_partials_jobs_empty_returns_286(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_list(monkeypatch, [])
        resp = client.get("/partials/jobs")
    assert resp.status_code == 286  # empty table → stop polling
    assert "No jobs yet" in resp.text


def test_partials_jobs_all_terminal_returns_286(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = [
        _job(JobStatus.done, mode="http", started=True, finished=True),
        _job(JobStatus.error, started=True, finished=True),
    ]
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_list(monkeypatch, jobs)
        resp = client.get("/partials/jobs")
    assert resp.status_code == 286  # all terminal → stop polling
    assert "jobs-table" in resp.text
    assert jobs[0].id in resp.text and jobs[1].id in resp.text


def test_partials_jobs_active_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = [
        _job(JobStatus.queued),
        _job(JobStatus.done, mode="http", started=True, finished=True),
    ]
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_list(monkeypatch, jobs)
        resp = client.get("/partials/jobs")
    assert resp.status_code == 200  # a non-terminal job → keep polling
    assert "status-queued" in resp.text


def test_partials_jobs_renders_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _job(JobStatus.running, mode="browser", started=True)  # finished unset → —
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_list(monkeypatch, [job])
        resp = client.get("/partials/jobs")
    body = resp.text
    assert resp.status_code == 200
    assert job.id in body
    assert "running" in body and "browser" in body
    assert "14:02:11" in body  # created/started time, UTC HH:MM:SS
    assert "—" in body  # finished is unset


async def _fake_run_job_noop(job_id: str, *, app_state) -> None:
    """No-op runner: a submitted job stays `queued` so the partial has a live row."""
    return None


def test_partials_jobs_integration_shows_submitted_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "run_job", _fake_run_job_noop)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.post("/submit", data=_FORM)
        resp = client.get("/partials/jobs")
    assert resp.status_code == 200  # the submitted job is still queued
    assert "jobs-table" in resp.text
    assert "status-queued" in resp.text


# --- F19: GET /jobs/{id}/view (single-job detail page) ---


def _detail_job(
    status: JobStatus,
    *,
    result: dict | None = None,
    error: str | None = None,
    mode: str | None = None,
    started: bool = False,
    finished: bool = False,
    fetch_ms: int | None = None,
    extract_ms: int | None = None,
    total_ms: int | None = None,
    content_truncated: bool | None = None,
) -> Job:
    """Build a Job carrying a result/error for the detail-page tests."""
    return Job(
        id=str(uuid.uuid4()),
        status=status,
        request=ExtractRequest(url="https://example.com/", prompt="get the title"),
        mode=mode,
        result=result,
        error=error,
        created_at=_STAMP,
        started_at=_STAMP if started else None,
        finished_at=_STAMP if finished else None,
        fetch_ms=fetch_ms,
        extract_ms=extract_ms,
        total_ms=total_ms,
        content_truncated=content_truncated,
    )


def _patch_get(monkeypatch: pytest.MonkeyPatch, job: Job | None) -> None:
    """Make the live store's `get()` return `job` (None to exercise the 404 path)."""

    async def _get(job_id: str) -> Job | None:
        return job

    monkeypatch.setattr(app.state.job_store, "get", _get)


def test_job_detail_done_renders_result(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _detail_job(
        JobStatus.done,
        result={"title": "Hello"},
        mode="http",
        started=True,
        finished=True,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/view")
    body = resp.text
    assert resp.status_code == 200
    assert job.id in body
    assert "result-json" in body  # the <pre> result block rendered
    assert "title" in body and "Hello" in body


def test_job_detail_shows_timing_and_truncation_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _detail_job(
        JobStatus.done,
        result={"title": "Hello"},
        mode="http",
        started=True,
        finished=True,
        fetch_ms=120,
        extract_ms=950,
        total_ms=1100,
        content_truncated=True,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/view")
    body = resp.text
    assert resp.status_code == 200
    assert "120 ms" in body and "950 ms" in body and "1100 ms" in body
    assert "truncated" in body  # the lossy-truncation note rendered


def test_job_detail_error_renders_message(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _detail_job(
        JobStatus.error, error="fetch failed: timeout", started=True, finished=True
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/view")
    assert resp.status_code == 200
    assert "fetch failed: timeout" in resp.text


def test_job_detail_escapes_untrusted_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Untrusted scraped content in the result must never inject live HTML.
    job = _detail_job(
        JobStatus.done,
        result={"x": "<script>alert(1)</script>"},
        mode="http",
        started=True,
        finished=True,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/view")
    body = resp.text
    assert resp.status_code == 200
    assert "<script>alert(1)</script>" not in body  # not rendered as live markup
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body  # escaped to inert text


def test_job_detail_escapes_untrusted_error(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _detail_job(
        JobStatus.error,
        error="<img src=x onerror=alert(1)>",
        started=True,
        finished=True,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/view")
    body = resp.text
    assert resp.status_code == 200
    assert "<img src=x onerror=alert(1)>" not in body
    assert "&lt;img" in body


def test_job_detail_unknown_id_returns_404_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, None)
        resp = client.get("/jobs/does-not-exist/view")
    assert resp.status_code == 404
    assert "text/html" in resp.headers["content-type"]
    assert "Job not found" in resp.text  # the styled HTML state, not JSON


def test_job_detail_running_shows_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _detail_job(JobStatus.running, mode="browser", started=True)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/view")
    body = resp.text
    assert resp.status_code == 200
    assert "in progress" in body.lower()
    assert "result-json" not in body  # no result/error block while non-terminal


def test_jobs_table_links_to_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _job(JobStatus.queued)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_list(monkeypatch, [job])
        resp = client.get("/partials/jobs")
    assert f'href="/jobs/{job.id}/view"' in resp.text


# --- F20: GET /jobs/{id}/export (JSON/CSV download) ---


def test_export_json_equals_stored_result(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _detail_job(
        JobStatus.done,
        result={"items": [{"a": 1}, {"a": 2}]},
        mode="http",
        started=True,
        finished=True,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/export?format=json")
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition and f"job-{job.id}.json" in disposition
    assert json.loads(resp.text) == job.result


def test_export_defaults_to_json(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _detail_job(JobStatus.done, result={"a": 1}, started=True, finished=True)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/export")  # no ?format
    assert resp.status_code == 200
    assert json.loads(resp.text) == {"a": 1}


def test_export_csv_has_header_and_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _detail_job(
        JobStatus.done,
        result={"items": [{"a": 1}, {"a": 2, "b": 3}]},
        started=True,
        finished=True,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/export?format=csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert f"job-{job.id}.csv" in resp.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == ["a", "b"]
    assert rows[1] == ["1", ""]
    assert rows[2] == ["2", "3"]


def test_export_unknown_id_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, None)
        resp = client.get("/jobs/does-not-exist/export?format=json")
    assert resp.status_code == 404


def test_export_unfinished_job_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _detail_job(JobStatus.running, mode="browser", started=True)  # no result
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/export?format=json")
    assert resp.status_code == 409


def test_export_bad_format_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _detail_job(JobStatus.done, result={"a": 1}, started=True, finished=True)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/export?format=xml")
    assert resp.status_code == 422


def test_detail_done_shows_export_buttons(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _detail_job(
        JobStatus.done, result={"a": 1}, mode="http", started=True, finished=True
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/view")
    body = resp.text
    assert f"/jobs/{job.id}/export?format=json" in body
    assert f"/jobs/{job.id}/export?format=csv" in body


def test_detail_running_hides_export_buttons(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _detail_job(JobStatus.running, mode="browser", started=True)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        _patch_get(monkeypatch, job)
        resp = client.get(f"/jobs/{job.id}/view")
    assert "export?format=" not in resp.text

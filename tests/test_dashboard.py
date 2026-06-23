"""Tests for the dashboard (F17): GET / shell + the form-handling POST /submit.

The app runs a real lifespan (real `JobStore`/`Scheduler`); the pipeline seam
(`app.jobs.runner.run_job`) is stubbed so a submitted job terminates without touching
the network or an LLM. `base_url="http://127.0.0.1"` keeps the Host allow-listed; the
form POST is `application/x-www-form-urlencoded` (`client.post(data=...)`).
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.dashboard import routes
from app.jobs import runner, submission
from app.main import app

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

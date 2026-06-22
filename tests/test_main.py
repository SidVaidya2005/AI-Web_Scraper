"""Tests for the app skeleton: health, lifespan, Host allow-list, entry point."""

import pytest
from fastapi.testclient import TestClient

import app.__main__ as app_main
from app.config import get_settings
from app.fetching.browser import BrowserManager
from app.jobs.store import JobStore
from app.main import app


def test_health_returns_ok() -> None:
    with TestClient(app, base_url="http://127.0.0.1") as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_lifespan_starts_and_sets_settings_state() -> None:
    # Entering the context triggers startup; exiting triggers a clean shutdown.
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/health").status_code == 200
        assert app.state.settings is get_settings()


def test_lifespan_wires_browser_manager_without_launching_chromium() -> None:
    # The BrowserManager is owned by the lifespan, but a request flow that never
    # renders must not launch Chromium (the opt-in-render guarantee, app level).
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/health").status_code == 200
        manager = app.state.browser_manager
        assert isinstance(manager, BrowserManager)
        assert manager._browser is None  # lazy: never launched on an HTTP-only run
    # Exiting the context ran aclose() cleanly (a no-op since it never launched).
    assert app.state.browser_manager._browser is None


def test_lifespan_wires_job_store() -> None:
    # The runner (F14) reads app.state.job_store; the lifespan must expose it.
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/health").status_code == 200
        assert isinstance(app.state.job_store, JobStore)


def test_disallowed_host_rejected() -> None:
    with TestClient(app, base_url="http://evil.com") as client:
        resp = client.get("/health")
    assert resp.status_code == 400


def test_entrypoint_honors_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app_path: str, **kwargs: object) -> None:
        captured["app_path"] = app_path
        captured.update(kwargs)

    monkeypatch.setattr(app_main.uvicorn, "run", fake_run)
    app_main.main()

    settings = get_settings()
    assert captured["app_path"] == "app.main:app"
    assert captured["host"] == settings.host
    assert captured["port"] == settings.port

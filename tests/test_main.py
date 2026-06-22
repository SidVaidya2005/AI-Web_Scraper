"""Tests for the app skeleton: health, lifespan, Host allow-list, entry point."""

import pytest
from fastapi.testclient import TestClient

import app.__main__ as app_main
from app.config import get_settings
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

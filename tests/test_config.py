"""Tests for app.config.Settings: defaults, env overrides, and fail-fast rules."""

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings, get_settings

# Settings fields whose env vars are asserted as defaults — cleared so a value in
# the developer's shell can't bleed into the assertions.
_ASSERTED_DEFAULT_VARS = (
    "LLM_PROVIDER",
    "MAX_CONTENT_CHARS",
    "ALLOWED_HOSTS",
    "MAX_CONCURRENT_JOBS",
)


def test_defaults_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _ASSERTED_DEFAULT_VARS:
        monkeypatch.delenv(var, raising=False)
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "anthropic"
    assert settings.anthropic_model == "claude-sonnet-4-6"
    assert settings.max_content_chars == 50_000
    assert settings.allowed_hosts == ["127.0.0.1", "localhost"]
    assert settings.max_concurrent_jobs == 4
    assert settings.max_queued_jobs == 50
    assert settings.max_jobs == 500


def test_env_overrides_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "2")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-8")
    monkeypatch.setenv("ALLOWED_HOSTS", "a.com, b.com")
    settings = Settings(_env_file=None)
    assert settings.max_concurrent_jobs == 2
    assert settings.anthropic_model == "claude-opus-4-8"
    # comma-separated string is split (and whitespace stripped) into a list
    assert settings.allowed_hosts == ["a.com", "b.com"]


def test_relationship_violation_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # max_queued_jobs < max_concurrent_jobs breaks the cap chain
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "4")
    monkeypatch.setenv("MAX_QUEUED_JOBS", "3")
    with pytest.raises(ValidationError, match="max_concurrent_jobs"):
        Settings(_env_file=None)


def test_non_positive_cap_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FETCH_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_bad_provider_enum_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_api_key_is_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    settings = Settings(_env_file=None)
    assert isinstance(settings.anthropic_api_key, SecretStr)
    # the raw value never appears in repr/str — only via get_secret_value()
    assert "sk-secret-value" not in repr(settings)
    assert "sk-secret-value" not in str(settings.anthropic_api_key)
    assert settings.anthropic_api_key.get_secret_value() == "sk-secret-value"


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()

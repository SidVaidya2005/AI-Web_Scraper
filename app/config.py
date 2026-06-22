"""Typed application settings — the ONLY place env vars / `.env` are read."""

from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration, loaded once from environment / `.env`.

    Per-field positivity is enforced by `Field` constraints; the cross-field
    cap relationship is enforced by a model validator. Both fail fast at
    construction, never at request time.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM provider selection ---
    llm_provider: Literal["anthropic", "openai"] = "anthropic"

    # --- Anthropic (default provider) ---
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-sonnet-4-6"

    # --- OpenAI (optional second provider) ---
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""

    # --- LLM call ---
    llm_timeout_seconds: int = Field(default=60, gt=0)

    # --- Fetch (HTTP fast path) ---
    fetch_timeout_seconds: int = Field(default=15, gt=0)
    max_redirects: int = Field(default=5, gt=0)
    fetch_max_retries: int = Field(default=1, ge=0)
    max_response_bytes: int = Field(default=5_000_000, gt=0)
    allow_private_hosts: bool = False
    user_agent: str = Field(default="AI-Web-Scraper/0.1", min_length=1)

    # --- Render (browser fallback, opt-in via render=true) ---
    render_timeout_seconds: int = Field(default=30, gt=0)
    render_settle_ms: int = Field(default=500, ge=0)

    # --- Cleaning ---
    max_content_chars: int = Field(default=50_000, gt=0)

    # --- Respectful client ---
    respect_robots: bool = True
    rate_limit_per_host_per_minute: int = Field(default=30, gt=0)

    # --- Jobs (must satisfy max_concurrent_jobs <= max_queued_jobs <= max_jobs) ---
    max_concurrent_jobs: int = Field(default=4, gt=0)
    max_queued_jobs: int = Field(default=50, gt=0)
    max_jobs: int = Field(default=500, gt=0)
    shutdown_grace_seconds: int = Field(default=10, ge=0)
    job_ttl_seconds: int = Field(default=3600, gt=0)

    # --- Server / host (HOST/PORT honored only via `python -m app`) ---
    # NoDecode: stop pydantic-settings JSON-decoding the raw env value so the
    # comma-separated string (e.g. "127.0.0.1,localhost") reaches the splitter
    # below instead of failing as invalid JSON.
    allowed_hosts: Annotated[list[str], NoDecode] = ["127.0.0.1", "localhost"]
    host: str = "127.0.0.1"
    port: int = Field(default=8000, gt=0)

    # --- Logging ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_allowed_hosts(cls, value: object) -> object:
        """Parse a comma-separated env string into a list of hostnames."""
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value

    @model_validator(mode="after")
    def _check_job_cap_relationship(self) -> "Settings":
        """Enforce concurrency <= admission cap <= retention cap (fail fast)."""
        if not (self.max_concurrent_jobs <= self.max_queued_jobs <= self.max_jobs):
            raise ValueError(
                "job caps must satisfy "
                "max_concurrent_jobs <= max_queued_jobs <= max_jobs "
                f"(got {self.max_concurrent_jobs}, {self.max_queued_jobs}, "
                f"{self.max_jobs})"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance (FastAPI dependency)."""
    return Settings()


# FastAPI dependency alias: inject the cached Settings into a handler with
# `settings: SettingsDep`. Lives here (the settings' home) rather than in each
# router so there is one canonical way to obtain Settings in a request scope.
SettingsDep = Annotated[Settings, Depends(get_settings)]

"""Tests for app.fetching.respect (F21): the respectful-client gate.

The rate limiter is exercised with an injected clock so window-roll behavior is
deterministic without sleeping. The robots path monkeypatches
`http_fetcher.fetch` (the same seam style as the rest of the fetching tests) to
return crafted FetchResults / raise crafted errors — no real network, no real DNS.
"""

from typing import Any

import pytest

from app.config import Settings
from app.fetching import http_fetcher
from app.fetching.errors import (
    RateLimitedError,
    RobotsDisallowedError,
    SSRFError,
    TransientFetchError,
)
from app.fetching.models import FetchResult
from app.fetching.respect import RespectfulClient


def _settings(**overrides: Any) -> Settings:
    overrides.setdefault("anthropic_api_key", "test-key")
    return Settings(_env_file=None, **overrides)


class _Clock:
    """A controllable monotonic-style clock for deterministic window tests."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _robots_result(body: str, *, status: int = 200) -> FetchResult:
    return FetchResult(
        html=body,
        mode="http",
        status=status,
        content_type="text/plain",
        final_url="http://host/robots.txt",
    )


# --- rate limiter ---------------------------------------------------------


def test_under_limit_passes() -> None:
    client = RespectfulClient(_settings(rate_limit_per_host_per_minute=3))
    for _ in range(3):
        client.check_rate_limit("host")  # exactly at the cap, no overshoot


def test_over_limit_raises() -> None:
    client = RespectfulClient(_settings(rate_limit_per_host_per_minute=2))
    client.check_rate_limit("host")
    client.check_rate_limit("host")
    with pytest.raises(RateLimitedError):
        client.check_rate_limit("host")


def test_window_rolls_after_60s() -> None:
    clk = _Clock(0.0)
    client = RespectfulClient(_settings(rate_limit_per_host_per_minute=1), clock=clk)
    client.check_rate_limit("host")  # t=0 → window [0]
    clk.t = 30.0
    with pytest.raises(RateLimitedError):  # still inside the 60s window
        client.check_rate_limit("host")
    clk.t = 61.0  # the t=0 timestamp falls out of the window
    client.check_rate_limit("host")  # allowed again


def test_per_host_isolation() -> None:
    client = RespectfulClient(_settings(rate_limit_per_host_per_minute=1))
    client.check_rate_limit("a.example")
    client.check_rate_limit("b.example")  # separate window — not blocked
    with pytest.raises(RateLimitedError):
        client.check_rate_limit("a.example")  # a is now at its cap


# --- robots.txt -----------------------------------------------------------


async def test_respect_robots_false_skips_fetch(monkeypatch) -> None:
    called = False

    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        nonlocal called
        called = True
        return _robots_result("")

    monkeypatch.setattr(http_fetcher, "fetch", fake_fetch)
    client = RespectfulClient(_settings(respect_robots=False))
    await client.check_robots("http://host/page")  # must not raise or fetch
    assert called is False


async def test_robots_allows_when_path_not_disallowed(monkeypatch) -> None:
    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        return _robots_result("User-agent: *\nDisallow: /private")

    monkeypatch.setattr(http_fetcher, "fetch", fake_fetch)
    client = RespectfulClient(_settings())
    await client.check_robots("http://host/public")  # allowed → no raise


async def test_robots_disallows_blocks_matching_path(monkeypatch) -> None:
    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        return _robots_result("User-agent: *\nDisallow: /private")

    monkeypatch.setattr(http_fetcher, "fetch", fake_fetch)
    client = RespectfulClient(_settings())
    with pytest.raises(RobotsDisallowedError):
        await client.check_robots("http://host/private/secret")


async def test_robots_404_allows(monkeypatch) -> None:
    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        return _robots_result("", status=404)

    monkeypatch.setattr(http_fetcher, "fetch", fake_fetch)
    client = RespectfulClient(_settings())
    await client.check_robots("http://host/anything")  # fail-open → no raise


async def test_robots_5xx_allows(monkeypatch) -> None:
    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        return _robots_result("", status=503)

    monkeypatch.setattr(http_fetcher, "fetch", fake_fetch)
    client = RespectfulClient(_settings())
    await client.check_robots("http://host/anything")  # fail-open → no raise


async def test_robots_fetch_error_allows(monkeypatch) -> None:
    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        raise TransientFetchError("robots timed out")

    monkeypatch.setattr(http_fetcher, "fetch", fake_fetch)
    client = RespectfulClient(_settings())
    await client.check_robots("http://host/anything")  # fail-open → no raise


async def test_robots_ssrf_propagates(monkeypatch) -> None:
    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        raise SSRFError("blocked private address")

    monkeypatch.setattr(http_fetcher, "fetch", fake_fetch)
    client = RespectfulClient(_settings())
    with pytest.raises(SSRFError):  # never swallowed — guard is not bypassed
        await client.check_robots("http://host/anything")


async def test_robots_cache_hit_avoids_second_fetch(monkeypatch) -> None:
    calls = 0

    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        nonlocal calls
        calls += 1
        return _robots_result("User-agent: *\nDisallow: /private")

    monkeypatch.setattr(http_fetcher, "fetch", fake_fetch)
    client = RespectfulClient(_settings())
    await client.check_robots("http://host/public")
    await client.check_robots("http://host/other")  # same origin → cache hit
    assert calls == 1


async def test_guard_runs_rate_limit_then_robots(monkeypatch) -> None:
    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        return _robots_result("User-agent: *\nDisallow: /private")

    monkeypatch.setattr(http_fetcher, "fetch", fake_fetch)
    client = RespectfulClient(_settings(rate_limit_per_host_per_minute=1))
    await client.guard("http://host/public")  # under cap + allowed → passes
    with pytest.raises(RateLimitedError):  # second call to same host → over cap
        await client.guard("http://host/public")

"""Tests for app.fetching.http_fetcher: pinning, redirects, caps, error taxonomy.

DNS is mocked via the url_guard `_resolve` seam and HTTP via httpx.MockTransport
(injected through the `transport` param), so the suite never touches the network.
"""

from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.fetching import http_fetcher, url_guard
from app.fetching.errors import FetchError, SSRFError, TransientFetchError


def _settings(**overrides: Any) -> Settings:
    # Pin allow_private_hosts off explicitly so the dev shell can't bleed in.
    overrides.setdefault("allow_private_hosts", False)
    return Settings(_env_file=None, **overrides)


def _mock_resolve(
    mapping: dict[str, list[str]],
) -> Callable[[str, int], Coroutine[Any, Any, list[str]]]:
    async def _resolve(host: str, port: int) -> list[str]:
        return list(mapping[host])

    return _resolve


# --- success + IP pinning (the core SSRF guarantee) ---


async def test_success_returns_result_and_pins_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        url_guard, "_resolve", _mock_resolve({"example.com": ["93.184.216.34"]})
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html>hi</html>",
        )

    result = await http_fetcher.fetch(
        "https://example.com/path?q=1",
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )

    assert result.mode == "http"
    assert result.status == 200
    assert result.html == "<html>hi</html>"
    assert result.content_type == "text/html; charset=utf-8"
    assert result.final_url == "https://example.com/path?q=1"
    # Connected to the vetted IP, not the hostname; cert/SNI + routing stay on the host.
    assert len(seen) == 1
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["Host"] == "example.com"
    assert seen[0].extensions["sni_hostname"] == "example.com"


# --- non-2xx is returned, not raised (the F07 matrix decides) ---


async def test_non_2xx_is_returned_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        url_guard, "_resolve", _mock_resolve({"example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, headers={"content-type": "text/html"}, content=b"nope"
        )

    result = await http_fetcher.fetch(
        "http://example.com/",
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )
    assert result.status == 404
    assert result.status_ok is False


# --- transient errors ---


async def test_timeout_raises_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        url_guard, "_resolve", _mock_resolve({"example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    with pytest.raises(TransientFetchError):
        await http_fetcher.fetch(
            "http://example.com/",
            settings=_settings(),
            transport=httpx.MockTransport(handler),
        )


async def test_connect_error_raises_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        url_guard, "_resolve", _mock_resolve({"example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(TransientFetchError):
        await http_fetcher.fetch(
            "http://example.com/",
            settings=_settings(),
            transport=httpx.MockTransport(handler),
        )


# --- hard byte cap (NOT transient — an oversized page should not be retried) ---


async def test_oversized_body_raises_fetcherror_not_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        url_guard, "_resolve", _mock_resolve({"example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"x" * 100
        )

    with pytest.raises(FetchError) as exc_info:
        await http_fetcher.fetch(
            "http://example.com/",
            settings=_settings(max_response_bytes=10),
            transport=httpx.MockTransport(handler),
        )
    assert not isinstance(exc_info.value, TransientFetchError)


# --- redirects ---


async def test_too_many_redirects_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        url_guard, "_resolve", _mock_resolve({"example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://example.com/next"})

    with pytest.raises(FetchError) as exc_info:
        await http_fetcher.fetch(
            "http://example.com/",
            settings=_settings(max_redirects=2),
            transport=httpx.MockTransport(handler),
        )
    assert "too many redirects" in str(exc_info.value)
    assert not isinstance(exc_info.value, TransientFetchError)


async def test_redirect_to_blocked_address_raises_ssrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        url_guard, "_resolve", _mock_resolve({"example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        # First (only) hop redirects to the cloud-metadata endpoint.
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    with pytest.raises(SSRFError):
        await http_fetcher.fetch(
            "http://example.com/",
            settings=_settings(),
            transport=httpx.MockTransport(handler),
        )


async def test_redirect_followed_repins_each_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        url_guard,
        "_resolve",
        _mock_resolve({"a.example": ["93.184.216.34"], "b.example": ["1.1.1.1"]}),
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers["Host"] == "a.example":
            return httpx.Response(302, headers={"location": "http://b.example/final"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"ok")

    result = await http_fetcher.fetch(
        "http://a.example/start",
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )

    assert result.status == 200
    assert result.final_url == "http://b.example/final"
    assert [r.url.host for r in seen] == ["93.184.216.34", "1.1.1.1"]
    assert seen[1].headers["Host"] == "b.example"


async def test_relative_location_resolved_against_logical_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        url_guard, "_resolve", _mock_resolve({"example.com": ["93.184.216.34"]})
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.raw_path == b"/a/b":
            return httpx.Response(302, headers={"location": "/c"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"ok")

    result = await http_fetcher.fetch(
        "http://example.com/a/b",
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )
    assert result.final_url == "http://example.com/c"
    assert seen[1].url.raw_path == b"/c"
    assert seen[1].headers["Host"] == "example.com"


async def test_ipv6_pinned_ip_is_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        url_guard, "_resolve", _mock_resolve({"example.com": ["2606:4700::1111"]})
    )
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"ok")

    result = await http_fetcher.fetch(
        "http://example.com/",
        settings=_settings(),
        transport=httpx.MockTransport(handler),
    )
    assert result.status == 200
    assert seen[0].url.host == "2606:4700::1111"
    assert seen[0].headers["Host"] == "example.com"


# --- error taxonomy ---


def test_transient_is_a_fetcherror() -> None:
    assert issubclass(TransientFetchError, FetchError)

"""Tests for app.fetching.url_guard: scheme, IP classification, DNS, pinning.

DNS is mocked throughout (the `_resolve` seam) so the suite is deterministic and
never touches the live network.
"""

import asyncio
import socket
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from app.config import Settings
from app.fetching import url_guard
from app.fetching.errors import FetchError, SSRFError


def _settings(*, allow_private_hosts: bool = False) -> Settings:
    # Pin allow_private_hosts explicitly so a value in the dev shell can't bleed in.
    return Settings(_env_file=None, allow_private_hosts=allow_private_hosts)


def _mock_resolve(
    *addresses: str,
) -> Callable[[str, int], Coroutine[Any, Any, list[str]]]:
    async def _resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    return _resolve


# --- scheme allow-list ---


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "data:text/plain,hi",
        "gopher://example.com/",
    ],
)
async def test_non_http_scheme_rejected(url: str) -> None:
    with pytest.raises(FetchError):
        await url_guard.validate(url, settings=_settings())


async def test_missing_host_rejected() -> None:
    with pytest.raises(FetchError):
        await url_guard.validate("http:///path", settings=_settings())


# --- IP literals (no DNS) ---


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/",  # cloud metadata
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped IPv6
    ],
)
async def test_blocked_ip_literals_rejected(url: str) -> None:
    with pytest.raises(SSRFError):
        await url_guard.validate(url, settings=_settings())


async def test_public_ip_literal_passes_and_pins() -> None:
    host, ip = await url_guard.resolve_and_validate(
        "http://1.1.1.1/", settings=_settings()
    )
    assert host == "1.1.1.1"
    assert ip == "1.1.1.1"


# --- hostnames (DNS mocked) ---


async def test_localhost_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(url_guard, "_resolve", _mock_resolve("127.0.0.1"))
    with pytest.raises(SSRFError):
        await url_guard.validate("http://localhost/", settings=_settings())


async def test_public_hostname_passes_and_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(url_guard, "_resolve", _mock_resolve("93.184.216.34"))
    host, ip = await url_guard.resolve_and_validate(
        "http://example.com/path?q=1", settings=_settings()
    )
    assert host == "example.com"
    assert ip == "93.184.216.34"


async def test_public_hostname_resolving_private_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # DNS-rebinding style: a public-looking host that points at a private IP.
    monkeypatch.setattr(url_guard, "_resolve", _mock_resolve("10.0.0.5"))
    with pytest.raises(SSRFError):
        await url_guard.validate("http://evil.example.com/", settings=_settings())


async def test_multi_ip_any_blocked_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        url_guard, "_resolve", _mock_resolve("93.184.216.34", "10.0.0.5")
    )
    with pytest.raises(SSRFError):
        await url_guard.validate("http://example.com/", settings=_settings())


async def test_multi_ip_all_public_pins_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        url_guard, "_resolve", _mock_resolve("93.184.216.34", "1.1.1.1")
    )
    _, ip = await url_guard.resolve_and_validate(
        "http://example.com/", settings=_settings()
    )
    assert ip == "93.184.216.34"


# --- escape hatch ---


async def test_allow_private_hosts_permits_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(url_guard, "_resolve", _mock_resolve("127.0.0.1"))
    settings = _settings(allow_private_hosts=True)
    _, ip = await url_guard.resolve_and_validate("http://localhost/", settings=settings)
    assert ip == "127.0.0.1"
    # private IP literals are permitted too
    _, ip2 = await url_guard.resolve_and_validate("http://10.0.0.1/", settings=settings)
    assert ip2 == "10.0.0.1"


async def test_allow_private_hosts_still_enforces_scheme() -> None:
    with pytest.raises(FetchError):
        await url_guard.validate(
            "file:///etc/passwd", settings=_settings(allow_private_hosts=True)
        )


# --- resolution failure & taxonomy ---


async def test_resolve_maps_gaierror_to_fetcherror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()

    async def _fail(*args: Any, **kwargs: Any) -> list[Any]:
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(loop, "getaddrinfo", _fail)
    with pytest.raises(FetchError):
        await url_guard._resolve("nonexistent.invalid", 80)


async def test_ssrferror_is_a_fetcherror() -> None:
    # Callers catch the broad FetchError (e.g. the browser route handler).
    with pytest.raises(FetchError):
        await url_guard.validate("http://127.0.0.1/", settings=_settings())
    assert issubclass(SSRFError, FetchError)

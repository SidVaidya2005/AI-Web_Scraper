"""SSRF guard: validate a URL's scheme and resolved IP before any fetch.

Pure and stateless — re-callable for every redirect hop and sub-resource. It does
no page I/O; the only network it touches is DNS resolution. The HTTP fetcher pins
the IP returned by `resolve_and_validate` so it connects to the exact vetted
address, closing the DNS-rebinding resolve->connect race.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.config import Settings
from app.fetching.errors import FetchError, SSRFError

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORTS = {"http": 80, "https": 443}
# Cloud-metadata endpoint. It is link-local (already blocked), but checked
# explicitly for defense-in-depth against this best-known SSRF target.
_METADATA_IP = ipaddress.ip_address("169.254.169.254")

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _is_blocked(ip: _IPAddress) -> bool:
    """Return True when `ip` is not a publicly routable address."""
    # IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) must be judged by its embedded v4.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip == _METADATA_IP
        or ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _resolve(host: str, port: int) -> list[str]:
    """Resolve `host` to its de-duplicated IP strings; never blocks the loop.

    Maps a DNS failure to FetchError. Monkeypatched in tests so the suite never
    touches real DNS.
    """
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchError(f"could not resolve host {host!r}") from exc
    ordered: dict[str, None] = {}  # preserve order while de-duplicating
    for info in infos:
        ordered.setdefault(info[4][0], None)
    return list(ordered)


async def resolve_and_validate(url: str, *, settings: Settings) -> tuple[str, str]:
    """Validate `url` and return `(host, pinned_ip)` for connection pinning.

    Raises FetchError for a disallowed scheme, missing host, or DNS failure, and
    SSRFError if the host (or any address it resolves to) is non-public. The
    private-address block is disabled by `settings.allow_private_hosts`; the
    scheme allow-list always applies.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise FetchError(f"unsupported URL scheme {scheme or '(none)'!r}")
    host = parts.hostname
    if not host:
        raise FetchError("URL has no host")

    # An IP literal needs no DNS — classify and pin it directly.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not settings.allow_private_hosts and _is_blocked(literal):
            raise SSRFError(f"refusing to fetch non-public address {host!r}")
        return host, str(literal)

    port = parts.port or _DEFAULT_PORTS[scheme]
    addresses = await _resolve(host, port)
    if not addresses:
        raise FetchError(f"could not resolve host {host!r}")
    if not settings.allow_private_hosts:
        # Validate every resolved address; a single blocked record rejects the URL.
        for addr in addresses:
            if _is_blocked(ipaddress.ip_address(addr)):
                raise SSRFError(f"host {host!r} resolves to a non-public address")
    return host, addresses[0]  # pin the first vetted address


async def validate(url: str, *, settings: Settings) -> None:
    """Validate `url`, raising FetchError/SSRFError on rejection; pin discarded."""
    await resolve_and_validate(url, settings=settings)

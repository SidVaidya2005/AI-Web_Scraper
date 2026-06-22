"""The HTTP fast path: fetch raw HTML over httpx, safely and bounded.

Resolves and pins the validated IP before connecting (closing the DNS-rebinding
resolve->connect race), follows redirects manually so every hop is re-validated and
re-pinned, and streams the body with a hard pre-buffer size cap. Returns a rich
FetchResult; the render decision lives in app/fetching/fetch_service.py, not here.
"""

from urllib.parse import urljoin

import httpx

from app.config import Settings
from app.fetching import url_guard
from app.fetching.errors import FetchError, TransientFetchError
from app.fetching.models import FetchResult

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _bracket(host: str) -> str:
    """Bracket an IPv6 literal for use in a URL / Host header; pass others through."""
    return f"[{host}]" if ":" in host else host


async def fetch(
    url: str,
    *,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchResult:
    """Fetch `url` over HTTP and return a FetchResult (mode="http").

    Raises SSRFError for a blocked address (also on any redirect hop), FetchError for
    an oversized body or too many redirects, and TransientFetchError for a timeout or
    connection failure. A non-2xx response is returned, not raised — the fetch
    strategy decides what to do with it.
    """
    try:
        async with httpx.AsyncClient(
            timeout=settings.fetch_timeout_seconds,
            follow_redirects=False,  # re-validate + re-pin every hop ourselves
            headers={"User-Agent": settings.user_agent},
            transport=transport,  # None -> httpx builds the default transport
        ) as client:
            for _ in range(settings.max_redirects):
                # Resolve+validate against the LOGICAL url; pin the vetted IP so the
                # byte stream comes from the exact address we checked.
                host, pinned_ip = await url_guard.resolve_and_validate(
                    url, settings=settings
                )
                logical = httpx.URL(url)
                pinned = logical.copy_with(host=_bracket(pinned_ip))
                port = logical.port or _DEFAULT_PORTS[logical.scheme]
                host_hdr = _bracket(host)
                if logical.port is not None:
                    host_hdr = f"{host_hdr}:{port}"
                async with client.stream(
                    "GET",
                    pinned,
                    headers={"Host": host_hdr},
                    # SNI + cert verification stay on the hostname, not the IP.
                    extensions={"sni_hostname": host},
                ) as resp:
                    if resp.is_redirect:
                        # Resolve a relative Location against the logical url, never
                        # the pinned-IP url (which would drop the hostname).
                        url = urljoin(url, resp.headers["location"])
                        continue
                    content_type = resp.headers.get("content-type", "")
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > settings.max_response_bytes:
                            raise FetchError("response exceeded MAX_RESPONSE_BYTES")
                        chunks.append(chunk)
                    html = b"".join(chunks).decode(resp.encoding or "utf-8", "replace")
                    return FetchResult(
                        html=html,
                        mode="http",
                        status=resp.status_code,
                        content_type=content_type,
                        final_url=url,  # logical host url, never the pinned IP
                    )
    except httpx.TimeoutException as exc:
        raise TransientFetchError(f"fetch timed out for {url}") from exc
    except httpx.TransportError as exc:
        raise TransientFetchError(f"fetch failed for {url}") from exc

    raise FetchError("too many redirects")

"""Shared API security dependencies: the v1 CSRF Origin check.

A lenient cross-origin guard for state-changing routes (`POST /extract` now, the
dashboard form POST in F17). Paired with the Host allow-list (`TrustedHostMiddleware`),
it is the v1 DNS-rebinding/CSRF baseline — not authentication. Token-based CSRF and
real auth remain out of scope (see architecture.md → Invariants / Security model).
"""

from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def require_trusted_origin(request: Request) -> None:
    """Reject a state-changing request whose `Origin` host isn't allow-listed.

    Lenient by design: a missing `Origin` (non-browser API clients — curl, httpx,
    server-to-server — don't send one) is allowed; a *present* `Origin` whose host
    isn't in `ALLOWED_HOSTS` is rejected with 403. Use as a route dependency.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return
    allowed = request.app.state.settings.allowed_hosts
    host = urlsplit(origin).hostname
    if host is None or host not in allowed:
        raise HTTPException(status_code=403, detail="cross-origin request rejected")

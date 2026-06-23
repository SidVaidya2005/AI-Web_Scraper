"""Respectful-client gate: per-host rate limiting + robots.txt honoring.

`RespectfulClient.guard(url)` runs once per job (invoked by the runner) before the
fetch path, so the service is a polite web citizen: it caps how often it hits a
single host and obeys that host's robots.txt. Both are stateful (rate-limit windows
+ a robots cache), so the client lives on `app.state` and is injected.

The robots.txt body is fetched through the safe `http_fetcher` directly (so it goes
through `url_guard` + IP-pinning + the size cap) and parsed with stdlib
`RobotFileParser.parse` — never `RobotFileParser.read()`, which would do its own
blocking, unguarded `urlopen`. Fetching robots that way also avoids recursing back
through this gate.
"""

import logging
import time
from collections import deque
from collections.abc import Callable
from urllib.parse import SplitResult, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from app.config import Settings
from app.fetching import http_fetcher
from app.fetching.errors import (
    FetchError,
    RateLimitedError,
    RobotsDisallowedError,
    SSRFError,
)

logger = logging.getLogger("app.fetching")

_RATE_WINDOW_SECONDS = 60.0  # the "per minute" in RATE_LIMIT_PER_HOST_PER_MINUTE
_ROBOTS_CACHE_TTL_SECONDS = 3600.0  # re-fetch a host's robots.txt at most hourly


class RespectfulClient:
    """Per-host rate limiter + robots.txt cache, applied before a job's fetch.

    Holds a rolling-window timestamp deque per host and a TTL-cached
    `RobotFileParser` (or `None` for "no restrictions") per origin. `clock` is
    injectable so window-roll behavior is testable without sleeping.
    """

    def __init__(
        self, settings: Settings, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._windows: dict[str, deque[float]] = {}
        self._robots: dict[str, tuple[RobotFileParser | None, float]] = {}

    async def guard(self, url: str) -> None:
        """Run the full respectful-client gate; raise FetchError on rejection.

        Raises `RateLimitedError` when the host is over its per-minute cap and
        `RobotsDisallowedError` when robots.txt forbids the URL. An `SSRFError`
        from the robots.txt fetch propagates (the guard is never bypassed).
        """
        host = urlsplit(url).hostname or ""
        self.check_rate_limit(host)
        await self.check_robots(url)

    def check_rate_limit(self, host: str) -> None:
        """Record one request to `host`, raising `RateLimitedError` if over cap.

        Synchronous and atomic on the event loop: it prunes the window and
        appends with no `await` in between, so concurrent jobs can't overshoot.
        """
        limit = self._settings.rate_limit_per_host_per_minute
        now = self._clock()
        window = self._windows.setdefault(host, deque())
        cutoff = now - _RATE_WINDOW_SECONDS
        while window and window[0] <= cutoff:
            window.popleft()
        if len(window) >= limit:
            logger.warning("rate limit exceeded for host %r (%d/min)", host, limit)
            raise RateLimitedError(
                f"rate limit exceeded for host {host!r} ({limit}/min)"
            )
        window.append(now)

    async def check_robots(self, url: str) -> None:
        """Raise `RobotsDisallowedError` if robots.txt forbids `url` for our UA.

        A no-op when `RESPECT_ROBOTS` is off. Fail-open: a missing/4xx/5xx or
        unreachable robots.txt allows the fetch (an explicit Disallow still blocks).
        """
        if not self._settings.respect_robots:
            return
        parts = urlsplit(url)
        parser = await self._robots_for(parts)
        if parser is not None and not parser.can_fetch(self._settings.user_agent, url):
            logger.info("robots.txt disallows %s", url)
            raise RobotsDisallowedError(f"robots.txt disallows fetching {url}")

    async def _robots_for(self, parts: SplitResult) -> RobotFileParser | None:
        """Return the cached/fresh parser for the origin (`None` = allow all)."""
        origin = f"{parts.scheme}://{parts.netloc}"
        now = self._clock()
        cached = self._robots.get(origin)
        if cached is not None and now - cached[1] < _ROBOTS_CACHE_TTL_SECONDS:
            return cached[0]
        parser = await self._fetch_robots(parts)  # may raise SSRFError
        self._robots[origin] = (parser, now)
        return parser

    async def _fetch_robots(self, parts: SplitResult) -> RobotFileParser | None:
        """Fetch + parse the origin's robots.txt; `None` on any non-200 (fail-open).

        Uses `http_fetcher` directly so the request is SSRF-guarded and size-capped
        without re-entering this gate. An `SSRFError` propagates; any other
        `FetchError` (timeout/oversize/unreachable) is treated as "allow".
        """
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        try:
            result = await http_fetcher.fetch(robots_url, settings=self._settings)
        except SSRFError:
            raise  # never bypass the SSRF guard
        except FetchError as exc:
            logger.warning(
                "robots.txt unreachable for %s (%s) — allowing", robots_url, exc
            )
            return None
        if not result.status_ok:
            return None  # missing (4xx) or server error (5xx) — allow
        parser = RobotFileParser()
        parser.parse(result.html.splitlines())
        return parser

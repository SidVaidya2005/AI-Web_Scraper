"""Browser render (fallback): render JS-heavy pages with one shared Chromium.

`BrowserManager` owns a single Chromium, launched **lazily** on the first render
(never at startup, so HTTP-only runs never pay for it) and reused thereafter.
`render` drives an isolated context per page, guards every connection through the
SSRF `url_guard` (main nav + redirects + sub-resources), blocks WebSockets and
service workers, and returns a rich `FetchResult` built from the real navigation
response — never hardcoded metadata.

The browser path **cannot pin** the validated IP the way the HTTP fast path does,
so it re-validates each request URL and carries a documented residual
DNS-rebinding risk; its byte cap is best-effort (the HTTP path owns the hard cap).
"""

import asyncio

from playwright.async_api import (
    Browser,
    Response,
    Route,
    WebSocketRoute,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from app.config import Settings
from app.fetching import url_guard
from app.fetching.errors import FetchError
from app.fetching.models import FetchResult


class BrowserManager:
    """Owns the one shared Chromium, launched lazily on first use.

    Concurrent first-renders are serialized by a lock so exactly one browser is
    created; `aclose()` is a no-op if the browser was never launched.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pw = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> Browser:
        """Return the shared Chromium, launching it on first call (once)."""
        if self._browser is None:  # fast path: already launched
            async with self._lock:  # serialize concurrent first-renders
                if self._browser is None:  # re-check inside the lock
                    pw = await async_playwright().start()
                    try:
                        self._browser = await pw.chromium.launch(headless=True)
                    except BaseException:
                        await pw.stop()  # launch failed → don't leak the driver
                        raise
                    self._pw = pw  # record only after BOTH steps succeed
        return self._browser

    async def aclose(self) -> None:
        """Close the browser and stop the driver, iff they were ever started."""
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None


async def render(url: str, *, browser: Browser, settings: Settings) -> FetchResult:
    """Return a FetchResult with fully rendered HTML for `url` (mode="browser").

    Raises SSRFError/FetchError if the top URL is blocked by the guard, and
    FetchError if the rendered size exceeds MAX_RESPONSE_BYTES. A non-2xx or
    non-HTML response is returned (not raised) — the fetch strategy decides.
    """
    await url_guard.validate(url, settings=settings)  # fail fast before any context
    context = await browser.new_context(
        user_agent=settings.user_agent,
        # SW-intercepted fetches bypass context.route — block service workers so the
        # guard below covers every request.
        service_workers="block",
    )

    async def _guard(route: Route) -> None:
        # Runs for EVERY HTTP request: main nav, redirect hops, sub-resources.
        try:
            await url_guard.validate(route.request.url, settings=settings)
        except FetchError:
            await route.abort()
        else:
            await route.continue_()

    async def _block_ws(ws: WebSocketRoute) -> None:
        # WebSockets bypass context.route, can't be vetted by the http/https-scheme
        # guard (ws/wss) and can't be IP-pinned — block them all for SSRF safety.
        # Accepted rendering limitation: a page hydrated purely from a socket stream
        # won't fully render.
        await ws.close()

    total = 0  # cumulative declared-bytes budget (best-effort)

    def _on_response(resp: Response) -> None:
        nonlocal total
        try:
            total += int(resp.headers.get("content-length") or 0)
        except (TypeError, ValueError):
            pass  # missing/garbage header — budget is best-effort by design

    await context.route("**/*", _guard)
    await context.route_web_socket("**/*", _block_ws)
    context.on("response", _on_response)

    try:
        page = await context.new_page()
        response = await page.goto(
            url,
            wait_until="domcontentloaded",  # NOT networkidle (can hang on beacons)
            timeout=settings.render_timeout_seconds * 1000,  # Playwright uses ms
        )
        try:
            await page.wait_for_selector("body", timeout=settings.render_settle_ms)
        except PlaywrightTimeoutError:
            pass  # best-effort settle — render whatever is there
        await page.wait_for_timeout(settings.render_settle_ms)

        if total > settings.max_response_bytes:
            raise FetchError("rendered network exceeded MAX_RESPONSE_BYTES")
        html = await page.content()
        if len(html.encode("utf-8")) > settings.max_response_bytes:
            raise FetchError("rendered DOM exceeded MAX_RESPONSE_BYTES")

        return FetchResult(
            html=html,
            mode="browser",
            status=response.status if response else 0,
            content_type=response.headers.get("content-type", "") if response else "",
            final_url=page.url,  # after in-browser redirects
        )
    finally:
        await context.close()

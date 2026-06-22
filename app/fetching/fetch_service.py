"""The fetch strategy: HTTP fast path first, opt-in browser render as fallback.

Implements the fallback decision matrix from architecture.md — the single source of
truth for when an HTTP response is good enough and when (if the caller opted in) to
render with the browser. Returns a FetchResult; owns no job state.

Rendering is opt-in: with render=False the browser is never launched (``get()`` is
never awaited), and an outcome that would otherwise render becomes a FetchError. SSRF
rejections and other hard FetchErrors from the HTTP path propagate untouched.
"""

from selectolax.parser import HTMLParser

from app.config import Settings
from app.fetching import browser, http_fetcher
from app.fetching.errors import FetchError, TransientFetchError
from app.fetching.models import FetchResult

# A 2xx HTML body with fewer visible-text chars than this is treated as a JS shell
# that needs rendering. Coarse heuristic constant — tuning, not operator config.
_MIN_VISIBLE_TEXT_CHARS = 200
# Non-content nodes dropped before measuring text: a script-heavy SPA shell would
# otherwise look content-rich because its inlined JS counts as text.
_DROP_SELECTOR = "script, style, noscript, template"


def needs_render(html: str) -> bool:
    """Return True when `html` has too little visible text to extract from as-is.

    Runs only on the matrix's 2xx-HTML row. Drops non-content nodes first so an
    inlined-JS SPA shell (many bytes, no real text) is correctly flagged.
    """
    if not html or not html.strip():
        return True
    tree = HTMLParser(html)
    for node in tree.css(_DROP_SELECTOR):
        node.decompose()
    text = tree.body.text(separator=" ", strip=True) if tree.body else tree.text()
    return len(text) < _MIN_VISIBLE_TEXT_CHARS


def _insufficient_message(result: FetchResult) -> str:
    """A readable reason an HTTP result can't be used as-is (render not opted in)."""
    if not result.status_ok:
        return f"upstream returned HTTP {result.status}"
    if not result.is_html:
        return f"fetched non-HTML content {result.content_type!r}"
    return "page looks JavaScript-rendered — retry with render=true"


async def _fetch_http(url: str, *, settings: Settings) -> FetchResult:
    """Fetch over HTTP, retrying transient failures up to FETCH_MAX_RETRIES.

    Non-transient failures (SSRF, oversize, too-many-redirects) are not retried —
    they propagate on the first attempt.
    """
    last_exc: TransientFetchError | None = None
    for _ in range(settings.fetch_max_retries + 1):
        try:
            return await http_fetcher.fetch(url, settings=settings)
        except TransientFetchError as exc:
            last_exc = exc  # retry; non-transient errors propagate untouched
    assert last_exc is not None  # the loop always runs at least once
    raise last_exc


async def _render_and_check(
    url: str, *, browser_manager: browser.BrowserManager, settings: Settings
) -> FetchResult:
    """Render `url` and require a usable (2xx, HTML) result, else raise FetchError.

    Awaiting ``browser_manager.get()`` here is the point Chromium is first launched,
    so this is reached only on the render=True branch. A Playwright TimeoutError from
    render is left un-mapped (deferred to F21); FetchError/SSRFError propagate.
    """
    chromium = await browser_manager.get()
    rendered = await browser.render(url, browser=chromium, settings=settings)
    if rendered.status_ok and rendered.is_html:
        return rendered
    raise FetchError(
        f"render did not yield usable HTML (status {rendered.status}, "
        f"content-type {rendered.content_type!r})"
    )


async def fetch(
    url: str,
    *,
    browser_manager: browser.BrowserManager,
    settings: Settings,
    render: bool = False,
) -> FetchResult:
    """Fetch `url` per the architecture fallback matrix; return a FetchResult.

    Tries the HTTP fast path first. A usable 2xx HTML page is returned (mode="http").
    Otherwise, when render=True the page is rendered (mode="browser"); when
    render=False the browser is never launched and a FetchError is raised. A blocked
    URL (SSRFError) or other hard FetchError from the HTTP path propagates untouched.
    """
    try:
        result = await _fetch_http(url, settings=settings)
    except TransientFetchError:
        if not render:
            raise
        return await _render_and_check(
            url, browser_manager=browser_manager, settings=settings
        )

    if result.status_ok and result.is_html and not needs_render(result.html):
        return result
    if not render:
        raise FetchError(_insufficient_message(result))
    return await _render_and_check(
        url, browser_manager=browser_manager, settings=settings
    )

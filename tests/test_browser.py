"""Tests for app.fetching.browser: BrowserManager laziness + render() logic.

These are fully mock-based — no real Chromium and no network. Purpose-built fakes
stand in for the Playwright Browser/Context/Page/Response/Route surface that
render() touches, and a fake async_playwright seam drives BrowserManager. The
real-browser behavior (post-JS rendering) is covered by test_browser_integration.
"""

import asyncio
from typing import Any

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.config import Settings
from app.fetching import browser as browser_mod
from app.fetching.browser import BrowserManager, render
from app.fetching.errors import FetchError, SSRFError


def _settings(**overrides: Any) -> Settings:
    # Pin allow_private_hosts off explicitly so the dev shell can't bleed in.
    overrides.setdefault("allow_private_hosts", False)
    return Settings(_env_file=None, **overrides)


# --- fakes for the Playwright surface render() drives ---


class _FakeRequest:
    def __init__(self, url: str) -> None:
        self.url = url


class _FakeRoute:
    def __init__(self, url: str) -> None:
        self.request = _FakeRequest(url)
        self.aborted = False
        self.continued = False

    async def abort(self) -> None:
        self.aborted = True

    async def continue_(self) -> None:
        self.continued = True


class _FakeWebSocketRoute:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeResponse:
    def __init__(
        self, status: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        self.status = status
        self.headers = headers or {}


class _FakePage:
    def __init__(
        self,
        *,
        response: _FakeResponse,
        content: str,
        url: str,
        emit_lengths: list[int],
        selector_raises: bool,
        goto_raises: BaseException | None,
    ) -> None:
        self._context: _FakeContext | None = None
        self._response = response
        self._content = content
        self.url = url
        self._emit_lengths = emit_lengths
        self._selector_raises = selector_raises
        self._goto_raises = goto_raises

    async def goto(
        self, url: str, *, wait_until: str | None = None, timeout: float | None = None
    ) -> _FakeResponse:
        if self._goto_raises is not None:
            raise self._goto_raises
        # Simulate sub-resource responses hitting the content-length budget.
        assert self._context is not None
        for length in self._emit_lengths:
            self._context.fire_response(
                _FakeResponse(headers={"content-length": str(length)})
            )
        return self._response

    async def wait_for_selector(
        self, selector: str, *, timeout: float | None = None
    ) -> None:
        if self._selector_raises:
            raise PlaywrightTimeoutError("no body")

    async def wait_for_timeout(self, timeout: float) -> None:
        return None

    async def content(self) -> str:
        return self._content


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self._page = page
        page._context = self
        self._response_cb: Any = None
        self.closed = False
        self.guard_handler: Any = None
        self.ws_handler: Any = None

    async def route(self, pattern: str, handler: Any) -> None:
        self.guard_handler = handler

    async def route_web_socket(self, pattern: str, handler: Any) -> None:
        self.ws_handler = handler

    def on(self, event: str, cb: Any) -> None:
        if event == "response":
            self._response_cb = cb

    def fire_response(self, resp: _FakeResponse) -> None:
        if self._response_cb is not None:
            self._response_cb(resp)

    async def new_page(self) -> _FakePage:
        return self._page

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self._context = context
        self.new_context_calls: list[dict[str, Any]] = []

    async def new_context(self, **kwargs: Any) -> _FakeContext:
        self.new_context_calls.append(kwargs)
        return self._context


def _make_browser(
    *,
    response: _FakeResponse | None = None,
    content: str = "<html>ok</html>",
    url: str = "https://example.com/final",
    emit_lengths: list[int] | None = None,
    selector_raises: bool = False,
    goto_raises: BaseException | None = None,
) -> tuple[_FakeBrowser, _FakeContext, _FakePage]:
    if response is None:
        response = _FakeResponse(200, {"content-type": "text/html"})
    page = _FakePage(
        response=response,
        content=content,
        url=url,
        emit_lengths=emit_lengths or [],
        selector_raises=selector_raises,
        goto_raises=goto_raises,
    )
    context = _FakeContext(page)
    return _FakeBrowser(context), context, page


# --- render(): metadata, returned non-2xx, fail-fast, guards, caps, cleanup ---


async def test_render_builds_real_metadata() -> None:
    resp = _FakeResponse(201, {"content-type": "text/html; charset=utf-8"})
    browser, _, _ = _make_browser(
        response=resp, content="<html>hi</html>", url="https://example.com/final"
    )
    result = await render("http://1.1.1.1/", browser=browser, settings=_settings())
    assert result.mode == "browser"
    assert result.status == 201
    assert result.content_type == "text/html; charset=utf-8"
    assert result.final_url == "https://example.com/final"
    assert result.html == "<html>hi</html>"


async def test_non_2xx_is_returned_not_raised() -> None:
    resp = _FakeResponse(404, {"content-type": "application/json"})
    browser, _, _ = _make_browser(response=resp)
    result = await render("http://1.1.1.1/", browser=browser, settings=_settings())
    assert result.status == 404
    assert result.status_ok is False


async def test_blocked_top_url_rejected_before_context() -> None:
    browser, _, _ = _make_browser()
    with pytest.raises(SSRFError):
        await render("http://127.0.0.1/", browser=browser, settings=_settings())
    # Fail fast: no context is ever created for a blocked top URL.
    assert browser.new_context_calls == []


async def test_new_context_blocks_service_workers_and_sets_ua() -> None:
    browser, _, _ = _make_browser()
    settings = _settings()
    await render("http://1.1.1.1/", browser=browser, settings=settings)
    assert browser.new_context_calls[0]["service_workers"] == "block"
    assert browser.new_context_calls[0]["user_agent"] == settings.user_agent


async def test_route_guard_aborts_blocked_and_continues_allowed() -> None:
    browser, context, _ = _make_browser()
    await render("http://1.1.1.1/", browser=browser, settings=_settings())
    guard = context.guard_handler

    blocked = _FakeRoute("http://169.254.169.254/")  # cloud metadata
    await guard(blocked)
    assert blocked.aborted is True
    assert blocked.continued is False

    allowed = _FakeRoute("http://1.1.1.1/")
    await guard(allowed)
    assert allowed.continued is True
    assert allowed.aborted is False


async def test_websocket_handler_closes_all() -> None:
    browser, context, _ = _make_browser()
    await render("http://1.1.1.1/", browser=browser, settings=_settings())
    ws = _FakeWebSocketRoute()
    await context.ws_handler(ws)
    assert ws.closed is True


async def test_content_length_budget_exceeded_raises() -> None:
    browser, context, _ = _make_browser(emit_lengths=[2000])
    with pytest.raises(FetchError) as exc_info:
        await render(
            "http://1.1.1.1/",
            browser=browser,
            settings=_settings(max_response_bytes=1000),
        )
    assert not isinstance(exc_info.value, SSRFError)
    assert context.closed is True  # finally ran


async def test_post_render_backstop_raises() -> None:
    browser, context, _ = _make_browser(content="x" * 2000)
    with pytest.raises(FetchError):
        await render(
            "http://1.1.1.1/",
            browser=browser,
            settings=_settings(max_response_bytes=1000),
        )
    assert context.closed is True


async def test_context_closed_even_when_goto_raises() -> None:
    browser, context, _ = _make_browser(goto_raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await render("http://1.1.1.1/", browser=browser, settings=_settings())
    assert context.closed is True


async def test_render_timeout_mapped_to_fetch_error() -> None:
    # A goto timeout (F06/F07-deferred) becomes a readable FetchError, not the raw
    # Playwright error the runner would record as a generic "internal error".
    browser, context, _ = _make_browser(
        goto_raises=PlaywrightTimeoutError("nav timeout")
    )
    with pytest.raises(FetchError) as exc_info:
        await render("http://1.1.1.1/", browser=browser, settings=_settings())
    assert not isinstance(exc_info.value, SSRFError)
    assert "timed out" in str(exc_info.value)
    assert context.closed is True  # finally still ran


async def test_settle_timeout_is_swallowed() -> None:
    # A missing <body> makes wait_for_selector time out; render still succeeds.
    browser, _, _ = _make_browser(selector_raises=True, content="<html>late</html>")
    result = await render("http://1.1.1.1/", browser=browser, settings=_settings())
    assert result.html == "<html>late</html>"


# --- BrowserManager: lazy launch, concurrency, aclose, launch failure ---


class _FakeBrowserObj:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, fail: bool = False) -> None:
        self._fail = fail
        self.launch_calls = 0

    async def launch(self, headless: bool = True) -> _FakeBrowserObj:
        self.launch_calls += 1
        await asyncio.sleep(0)  # yield so the concurrency test can interleave
        if self._fail:
            raise RuntimeError("launch boom")
        return _FakeBrowserObj()


class _FakePlaywright:
    def __init__(self, fail: bool = False) -> None:
        self.chromium = _FakeChromium(fail)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class _FakePlaywrightStarter:
    def __init__(self, pw: _FakePlaywright) -> None:
        self._pw = pw

    async def start(self) -> _FakePlaywright:
        return self._pw


def _patch_playwright(monkeypatch: pytest.MonkeyPatch, pw: _FakePlaywright) -> None:
    monkeypatch.setattr(
        browser_mod, "async_playwright", lambda: _FakePlaywrightStarter(pw)
    )


async def test_browser_launched_lazily_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pw = _FakePlaywright()
    _patch_playwright(monkeypatch, pw)
    mgr = BrowserManager(_settings())
    browsers = await asyncio.gather(*(mgr.get() for _ in range(8)))
    assert pw.chromium.launch_calls == 1  # one browser despite concurrent first-renders
    assert all(b is browsers[0] for b in browsers)
    await mgr.aclose()


async def test_aclose_is_noop_when_never_launched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pw = _FakePlaywright()
    _patch_playwright(monkeypatch, pw)
    mgr = BrowserManager(_settings())
    await mgr.aclose()  # must not raise or launch anything
    assert pw.chromium.launch_calls == 0
    assert pw.stopped is False


async def test_aclose_closes_browser_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pw = _FakePlaywright()
    _patch_playwright(monkeypatch, pw)
    mgr = BrowserManager(_settings())
    obj = await mgr.get()
    await mgr.aclose()
    assert obj.closed is True
    assert pw.stopped is True
    await mgr.aclose()  # second call is a safe no-op


async def test_launch_failure_stops_driver_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pw = _FakePlaywright(fail=True)
    _patch_playwright(monkeypatch, pw)
    mgr = BrowserManager(_settings())
    with pytest.raises(RuntimeError):
        await mgr.get()
    assert pw.stopped is True  # driver stopped — no leak
    assert mgr._browser is None  # state allows a later retry

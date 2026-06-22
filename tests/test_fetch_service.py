"""Tests for app.fetching.fetch_service: the fallback decision matrix.

The HTTP fetcher and browser render are patched at their module seams (no real
network or browser); a FakeBrowserManager records whether the browser was ever
requested, so render=False can be asserted to never launch Chromium.
"""

from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.config import Settings
from app.fetching import browser, fetch_service, http_fetcher
from app.fetching.errors import FetchError, SSRFError, TransientFetchError
from app.fetching.models import FetchResult

# Body text well over the visible-text threshold vs. an empty SPA shell whose only
# bytes are inlined script (zero real text once script is dropped).
_RICH_HTML = "<html><body>" + ("real words here " * 40) + "</body></html>"
_SPA_HTML = (
    '<html><body><div id="root"></div>'
    "<script>" + ("x" * 5000) + "</script></body></html>"
)


def _settings(**overrides: Any) -> Settings:
    # Pin allow_private_hosts off explicitly so the dev shell can't bleed in.
    overrides.setdefault("allow_private_hosts", False)
    return Settings(_env_file=None, **overrides)


def _result(
    *,
    html: str = _RICH_HTML,
    status: int = 200,
    content_type: str = "text/html",
    mode: str = "http",
    final_url: str = "http://example.com/",
) -> FetchResult:
    return FetchResult(
        html=html,
        mode=mode,
        status=status,
        content_type=content_type,
        final_url=final_url,
    )


_FetchFn = Callable[..., Coroutine[Any, Any, FetchResult]]


def _fake_fetch(behaviors: list[Any], calls: list[str]) -> _FetchFn:
    """Build a fake http_fetcher.fetch: one behavior consumed per call.

    A behavior is a FetchResult to return or an Exception to raise.
    """
    seq = iter(behaviors)

    async def _fetch(url: str, **kwargs: Any) -> FetchResult:
        calls.append(url)
        item = next(seq)
        if isinstance(item, Exception):
            raise item
        return item

    return _fetch


def _fake_render(outcome: Any, calls: list[str]) -> _FetchFn:
    """Build a fake browser.render returning `outcome` (or raising it if Exception)."""

    async def _render(url: str, *, browser: Any, settings: Settings) -> FetchResult:
        calls.append(url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return _render


class _FakeBrowserManager:
    """Stands in for BrowserManager; records whether the browser was requested."""

    def __init__(self) -> None:
        self.get_calls = 0

    async def get(self) -> object:
        self.get_calls += 1
        return object()  # sentinel "Browser" — render is patched, so it is unused


# --- 2xx HTML, enough text: HTTP path, browser never touched (both flags) ---


@pytest.mark.parametrize("render", [False, True])
async def test_http_ok_returns_http_no_browser(
    monkeypatch: pytest.MonkeyPatch, render: bool
) -> None:
    http_calls: list[str] = []
    render_calls: list[str] = []
    monkeypatch.setattr(http_fetcher, "fetch", _fake_fetch([_result()], http_calls))
    monkeypatch.setattr(browser, "render", _fake_render(_result(), render_calls))
    fbm = _FakeBrowserManager()

    result = await fetch_service.fetch(
        "http://example.com/", browser_manager=fbm, settings=_settings(), render=render
    )

    assert result.mode == "http"
    assert http_calls == ["http://example.com/"]
    assert render_calls == []
    assert fbm.get_calls == 0


# --- SPA shell (needs_render True) ---


async def test_spa_shell_render_true_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    render_calls: list[str] = []
    monkeypatch.setattr(
        http_fetcher, "fetch", _fake_fetch([_result(html=_SPA_HTML)], [])
    )
    monkeypatch.setattr(
        browser, "render", _fake_render(_result(mode="browser"), render_calls)
    )
    fbm = _FakeBrowserManager()

    result = await fetch_service.fetch(
        "http://example.com/", browser_manager=fbm, settings=_settings(), render=True
    )

    assert result.mode == "browser"
    assert render_calls == ["http://example.com/"]
    assert fbm.get_calls == 1


async def test_spa_shell_render_false_errors_no_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render_calls: list[str] = []
    monkeypatch.setattr(
        http_fetcher, "fetch", _fake_fetch([_result(html=_SPA_HTML)], [])
    )
    monkeypatch.setattr(browser, "render", _fake_render(_result(), render_calls))
    fbm = _FakeBrowserManager()

    with pytest.raises(FetchError) as exc_info:
        await fetch_service.fetch(
            "http://example.com/",
            browser_manager=fbm,
            settings=_settings(),
            render=False,
        )

    assert "render=true" in str(exc_info.value)
    assert render_calls == []
    assert fbm.get_calls == 0


# --- non-HTML content-type ---


async def test_non_html_render_false_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        http_fetcher,
        "fetch",
        _fake_fetch([_result(content_type="application/json")], []),
    )
    fbm = _FakeBrowserManager()

    with pytest.raises(FetchError) as exc_info:
        await fetch_service.fetch(
            "http://example.com/",
            browser_manager=fbm,
            settings=_settings(),
            render=False,
        )

    assert "non-HTML" in str(exc_info.value)
    assert fbm.get_calls == 0


async def test_non_html_render_true_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    render_calls: list[str] = []
    monkeypatch.setattr(
        http_fetcher,
        "fetch",
        _fake_fetch([_result(content_type="application/json")], []),
    )
    monkeypatch.setattr(
        browser, "render", _fake_render(_result(mode="browser"), render_calls)
    )
    fbm = _FakeBrowserManager()

    result = await fetch_service.fetch(
        "http://example.com/", browser_manager=fbm, settings=_settings(), render=True
    )

    assert result.mode == "browser"
    assert fbm.get_calls == 1


# --- non-2xx ---


async def test_non_2xx_render_false_errors_with_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http_fetcher, "fetch", _fake_fetch([_result(status=404)], []))
    fbm = _FakeBrowserManager()

    with pytest.raises(FetchError) as exc_info:
        await fetch_service.fetch(
            "http://example.com/",
            browser_manager=fbm,
            settings=_settings(),
            render=False,
        )

    assert "404" in str(exc_info.value)
    assert fbm.get_calls == 0


async def test_non_2xx_render_true_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_fetcher, "fetch", _fake_fetch([_result(status=503)], []))
    monkeypatch.setattr(browser, "render", _fake_render(_result(mode="browser"), []))
    fbm = _FakeBrowserManager()

    result = await fetch_service.fetch(
        "http://example.com/", browser_manager=fbm, settings=_settings(), render=True
    )

    assert result.mode == "browser"
    assert fbm.get_calls == 1


# --- transient retry (the bounded-retry row) ---


async def test_transient_retried_then_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_calls: list[str] = []
    render_calls: list[str] = []
    monkeypatch.setattr(
        http_fetcher,
        "fetch",
        _fake_fetch([TransientFetchError("t"), _result()], http_calls),
    )
    monkeypatch.setattr(browser, "render", _fake_render(_result(), render_calls))
    fbm = _FakeBrowserManager()

    result = await fetch_service.fetch(
        "http://example.com/",
        browser_manager=fbm,
        settings=_settings(fetch_max_retries=1),
        render=False,
    )

    assert result.mode == "http"
    assert len(http_calls) == 2  # original + one retry
    assert render_calls == []
    assert fbm.get_calls == 0


async def test_transient_exhausted_render_false_raises_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_calls: list[str] = []
    monkeypatch.setattr(
        http_fetcher,
        "fetch",
        _fake_fetch([TransientFetchError("a"), TransientFetchError("b")], http_calls),
    )
    fbm = _FakeBrowserManager()

    with pytest.raises(TransientFetchError):
        await fetch_service.fetch(
            "http://example.com/",
            browser_manager=fbm,
            settings=_settings(fetch_max_retries=1),
            render=False,
        )

    assert len(http_calls) == 2
    assert fbm.get_calls == 0


async def test_transient_exhausted_render_true_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_calls: list[str] = []
    render_calls: list[str] = []
    monkeypatch.setattr(
        http_fetcher,
        "fetch",
        _fake_fetch([TransientFetchError("a"), TransientFetchError("b")], http_calls),
    )
    monkeypatch.setattr(
        browser, "render", _fake_render(_result(mode="browser"), render_calls)
    )
    fbm = _FakeBrowserManager()

    result = await fetch_service.fetch(
        "http://example.com/",
        browser_manager=fbm,
        settings=_settings(fetch_max_retries=1),
        render=True,
    )

    assert result.mode == "browser"
    assert len(http_calls) == 2
    assert render_calls == ["http://example.com/"]


async def test_retry_count_respects_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_calls: list[str] = []
    monkeypatch.setattr(
        http_fetcher,
        "fetch",
        _fake_fetch([TransientFetchError("t")] * 4, http_calls),
    )
    fbm = _FakeBrowserManager()

    with pytest.raises(TransientFetchError):
        await fetch_service.fetch(
            "http://example.com/",
            browser_manager=fbm,
            settings=_settings(fetch_max_retries=3),
            render=False,
        )

    assert len(http_calls) == 4  # fetch_max_retries + 1 attempts


# --- SSRF / hard errors are not retried and never render ---


async def test_ssrf_propagates_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    http_calls: list[str] = []
    render_calls: list[str] = []
    monkeypatch.setattr(
        http_fetcher,
        "fetch",
        _fake_fetch([SSRFError("blocked")], http_calls),
    )
    monkeypatch.setattr(browser, "render", _fake_render(_result(), render_calls))
    fbm = _FakeBrowserManager()

    with pytest.raises(SSRFError):
        await fetch_service.fetch(
            "http://example.com/",
            browser_manager=fbm,
            settings=_settings(fetch_max_retries=3),
            render=True,  # even opted in, a blocked URL is never rendered
        )

    assert len(http_calls) == 1  # not retried
    assert render_calls == []
    assert fbm.get_calls == 0


# --- rendered result must itself be usable ---


async def test_render_non_2xx_raises_fetcherror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        http_fetcher, "fetch", _fake_fetch([_result(html=_SPA_HTML)], [])
    )
    monkeypatch.setattr(
        browser, "render", _fake_render(_result(status=502, mode="browser"), [])
    )
    fbm = _FakeBrowserManager()

    with pytest.raises(FetchError, match="render did not yield usable HTML"):
        await fetch_service.fetch(
            "http://example.com/",
            browser_manager=fbm,
            settings=_settings(),
            render=True,
        )


async def test_render_non_html_raises_fetcherror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        http_fetcher, "fetch", _fake_fetch([_result(html=_SPA_HTML)], [])
    )
    monkeypatch.setattr(
        browser,
        "render",
        _fake_render(_result(content_type="application/pdf", mode="browser"), []),
    )
    fbm = _FakeBrowserManager()

    with pytest.raises(FetchError, match="render did not yield usable HTML"):
        await fetch_service.fetch(
            "http://example.com/",
            browser_manager=fbm,
            settings=_settings(),
            render=True,
        )


# --- render failures: timeout un-mapped (F21), SSRF propagates ---


async def test_render_timeout_propagates_unmapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        http_fetcher, "fetch", _fake_fetch([_result(html=_SPA_HTML)], [])
    )
    monkeypatch.setattr(
        browser, "render", _fake_render(PlaywrightTimeoutError("slow"), [])
    )
    fbm = _FakeBrowserManager()

    # Render-timeout -> readable job error is deferred to F21; here it propagates raw.
    with pytest.raises(PlaywrightTimeoutError):
        await fetch_service.fetch(
            "http://example.com/",
            browser_manager=fbm,
            settings=_settings(),
            render=True,
        )


async def test_render_ssrf_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        http_fetcher, "fetch", _fake_fetch([_result(html=_SPA_HTML)], [])
    )
    monkeypatch.setattr(
        browser, "render", _fake_render(SSRFError("blocked sub-resource"), [])
    )
    fbm = _FakeBrowserManager()

    with pytest.raises(SSRFError):
        await fetch_service.fetch(
            "http://example.com/",
            browser_manager=fbm,
            settings=_settings(),
            render=True,
        )


# --- needs_render heuristic ---


@pytest.mark.parametrize("html", ["", "   ", "\n\t "])
def test_needs_render_empty_true(html: str) -> None:
    assert fetch_service.needs_render(html) is True


def test_needs_render_spa_shell_true() -> None:
    assert fetch_service.needs_render(_SPA_HTML) is True


def test_needs_render_rich_false() -> None:
    assert fetch_service.needs_render(_RICH_HTML) is False


def test_needs_render_text_fragment_false() -> None:
    # A bare fragment with real text (no <body>) still has enough visible text.
    assert fetch_service.needs_render("<p>" + ("word " * 60) + "</p>") is False

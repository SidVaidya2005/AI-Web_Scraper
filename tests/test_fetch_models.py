"""Tests for app.fetching.models.FetchResult — the fetch contract + helpers."""

import pytest

from app.fetching.models import FetchResult


def _result(*, status: int = 200, content_type: str = "text/html") -> FetchResult:
    return FetchResult(
        html="<html></html>",
        mode="http",
        status=status,
        content_type=content_type,
        final_url="http://example.com/",
    )


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_status_ok_true_for_2xx(status: int) -> None:
    assert _result(status=status).status_ok is True


@pytest.mark.parametrize("status", [199, 300, 301, 404, 500])
def test_status_ok_false_outside_2xx(status: int) -> None:
    assert _result(status=status).status_ok is False


@pytest.mark.parametrize(
    "content_type",
    [
        "text/html",
        "text/html; charset=utf-8",
        "TEXT/HTML",
        "application/xhtml+xml",
        "",  # missing content-type is treated leniently as HTML on the fast path
    ],
)
def test_is_html_true(content_type: str) -> None:
    assert _result(content_type=content_type).is_html is True


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "text/plain", "image/png", "application/pdf"],
)
def test_is_html_false(content_type: str) -> None:
    assert _result(content_type=content_type).is_html is False


def test_fetch_result_is_frozen() -> None:
    result = _result()
    with pytest.raises((AttributeError, TypeError)):
        result.status = 500  # type: ignore[misc]

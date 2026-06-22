"""Tests for app.cleaning.cleaner.clean: boilerplate strip + character-budget trim.

Pure function — no network, no browser, no job state — so tests just feed HTML and
assert the trimmed text. Settings are built with `_env_file=None` so a real `.env`
or the dev shell can't bleed the cap in.
"""

from typing import Any

from app.cleaning.cleaner import clean
from app.config import Settings

# Distinctive markers inside every boilerplate node we drop, plus real content. If a
# marker survives, that node wasn't stripped; the content marker must always survive.
_NOISY_HTML = """
<html>
  <head><style>.brand{color:red} STYLEMARKER</style></head>
  <body>
    <nav>NAVMARKER</nav>
    <header>HEADERMARKER</header>
    <script>var SCRIPTMARKER = 1;</script>
    <noscript>NOSCRIPTMARKER</noscript>
    <svg><text>SVGMARKER</text></svg>
    <iframe>IFRAMEMARKER</iframe>
    <main><p>Real article content here.</p></main>
    <footer>FOOTERMARKER</footer>
  </body>
</html>
"""
_BOILERPLATE_MARKERS = [
    "STYLEMARKER",
    "NAVMARKER",
    "HEADERMARKER",
    "SCRIPTMARKER",
    "NOSCRIPTMARKER",
    "SVGMARKER",
    "IFRAMEMARKER",
    "FOOTERMARKER",
]


def _settings(**overrides: Any) -> Settings:
    # Pin the cap explicitly per test; default is the production 50_000.
    return Settings(_env_file=None, **overrides)


def test_boilerplate_nodes_are_stripped() -> None:
    result = clean(_NOISY_HTML, settings=_settings())
    assert "Real article content here." in result
    for marker in _BOILERPLATE_MARKERS:
        assert marker not in result


def test_truncates_to_max_content_chars() -> None:
    html = "<html><body>" + ("a" * 50) + "</body></html>"
    result = clean(html, settings=_settings(max_content_chars=20))
    assert len(result) == 20
    assert result == "a" * 20


def test_under_cap_returned_intact() -> None:
    html = "<html><body><p>Short content</p></body></html>"
    result = clean(html, settings=_settings(max_content_chars=50_000))
    assert result == "Short content"


def test_whitespace_is_stripped_at_edges() -> None:
    html = "<html><body>   Hello World   </body></html>"
    result = clean(html, settings=_settings())
    assert result == "Hello World"


def test_empty_html_returns_empty_string() -> None:
    assert clean("", settings=_settings()) == ""


def test_whitespace_only_html_returns_empty_string() -> None:
    assert clean("   \n\t  ", settings=_settings()) == ""


def test_fragment_without_body_still_yields_text() -> None:
    # A bare fragment (no <html>/<body>) must still return its text, never raise —
    # covers the `tree.text()` fallback branch for bodyless input.
    result = clean("<div>Fragment text</div>", settings=_settings())
    assert "Fragment text" in result

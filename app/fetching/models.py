"""The fetch contract: a FetchResult carries everything the fetch strategy needs.

Returning bare HTML would lose the status / content-type / final URL the fallback
matrix (app/fetching/fetch_service.py) branches on, so both fetch paths (httpx and
browser) return this richer result instead.
"""

from dataclasses import dataclass

# Content types treated as HTML on the fast path. An empty/missing content-type is
# treated leniently as HTML — the fetch succeeded, so hand it on; the render
# heuristic still filters genuinely empty bodies.
_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", ""})


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Rendered/raw HTML for a URL plus the metadata the strategy needs to branch."""

    html: str
    mode: str  # "http" | "browser"
    status: int  # final HTTP status
    content_type: str  # raw content-type header value
    final_url: str  # after redirects (already url_guard-validated)

    @property
    def status_ok(self) -> bool:
        """True when the final status is a 2xx success."""
        return 200 <= self.status < 300

    @property
    def is_html(self) -> bool:
        """True when the content-type is HTML (or absent — treated leniently)."""
        return self.content_type.split(";", 1)[0].strip().lower() in _HTML_CONTENT_TYPES

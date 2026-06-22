"""Real-Chromium integration test: prove post-JS content actually renders.

Unlike test_browser.py (fully mocked), this drives a real headless Chromium against
a self-contained SPA fixture served from a loopback HTTP server. It needs the
browser binary (`uv run playwright install chromium`); when that's absent the test
skips cleanly, so the suite still passes everywhere. CI installs the binary so it
runs there.

`allow_private_hosts=True` is the documented SSRF escape hatch (its stated purpose:
fetch localhost in tests) — required so the guard permits the loopback fixture.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from app.config import Settings
from app.fetching.browser import BrowserManager, render

# A SPA shell whose visible text is injected by JavaScript — empty over plain HTTP,
# populated only once a real browser executes the inline script.
_SPA_HTML = (
    b"<!doctype html><html><head><title>spa</title></head>"
    b'<body><div id="app"></div>'
    b"<script>document.getElementById('app').textContent = 'RENDERED_BY_JS';</script>"
    b"</body></html>"
)


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_SPA_HTML)))
        self.end_headers()
        self.wfile.write(_SPA_HTML)

    def log_message(self, *args: Any) -> None:
        pass  # keep the test output quiet


def _settings() -> Settings:
    # Loopback fixture → the SSRF block must be disabled for this test only.
    return Settings(_env_file=None, allow_private_hosts=True)


async def test_render_executes_javascript_on_local_fixture() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _, port = server.server_address
    base_url = f"http://127.0.0.1:{port}/"
    try:
        manager = BrowserManager(_settings())
        try:
            browser = await manager.get()  # exercises the real lazy launch
        except Exception as exc:  # binary not installed in this environment
            await manager.aclose()
            pytest.skip(
                f"Chromium not installed ({exc}); run `playwright install chromium`"
            )
        try:
            result = await render(base_url, browser=browser, settings=_settings())
        finally:
            await manager.aclose()
    finally:
        server.shutdown()
        server.server_close()

    # Proof the browser ran JS: the text exists only after the inline script fires.
    assert "RENDERED_BY_JS" in result.html
    assert result.mode == "browser"
    assert result.status == 200
    assert "text/html" in result.content_type
    assert result.final_url.rstrip("/") == base_url.rstrip("/")

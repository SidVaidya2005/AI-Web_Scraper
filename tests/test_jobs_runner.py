"""Tests for app.jobs.runner (F14): the pipeline driver / error boundary.

The runner is exercised against a **real** JobStore (in-memory, fast); the network
and LLM seams (`fetch_service.fetch`, `registry.get_provider`) are monkeypatched,
while `cleaner.clean` and `engine.extract` run for real where that strengthens the
test. `app_state` is a `SimpleNamespace` carrying the three deps run_job reads.

Pinned behaviors: happy path → done with result + fetch mode; known errors
(`FetchError`/`SSRFError`/`ProviderError`, plus a real schema mismatch) surface their
message verbatim; unknown errors yield a generic, non-leaky message; run_job never
raises even against an already-terminal or missing job; the URL is coerced to `str`
and the provider override is forwarded.
"""

import types
from typing import Any

from app.config import Settings
from app.fetching import fetch_service
from app.fetching.errors import FetchError, SSRFError
from app.fetching.models import FetchResult
from app.jobs.models import JobStatus
from app.jobs.runner import run_job
from app.jobs.store import JobStore
from app.models import ExtractRequest
from app.providers import registry
from app.providers.base import ProviderError

_HTML = "<html><body>Some real page content here</body></html>"


def _settings(**overrides: Any) -> Settings:
    overrides.setdefault("anthropic_api_key", "test-key")
    return Settings(_env_file=None, **overrides)


def _app_state(store: JobStore, settings: Settings) -> types.SimpleNamespace:
    # browser_manager is never touched (fetch is mocked); a sentinel is enough.
    return types.SimpleNamespace(
        job_store=store, browser_manager=object(), settings=settings
    )


def _fetch_result(*, mode: str = "http") -> FetchResult:
    return FetchResult(
        html=_HTML,
        mode=mode,
        status=200,
        content_type="text/html",
        final_url="https://example.com/",
    )


class _FakeProvider:
    """Structural LLMProvider: returns a fixed result or raises a primed error."""

    def __init__(
        self, *, result: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self._result = result
        self._error = error

    async def extract(
        self, *, content: str, prompt: str, json_schema: dict[str, Any] | None
    ) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


async def test_happy_path_marks_done_with_result_and_http_mode(monkeypatch) -> None:
    store = JobStore(settings=_settings())
    job = await store.create(
        ExtractRequest(url="https://example.com/", prompt="get it")
    )

    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        return _fetch_result()

    monkeypatch.setattr(fetch_service, "fetch", fake_fetch)
    monkeypatch.setattr(
        registry,
        "get_provider",
        lambda settings, *, override=None: _FakeProvider(result={"title": "Hello"}),
    )

    await run_job(job.id, app_state=_app_state(store, _settings()))

    done = await store.get(job.id)
    assert done is not None
    assert done.status is JobStatus.done
    assert done.result == {"title": "Hello"}
    assert done.mode == "http"
    assert done.started_at is not None
    assert done.finished_at is not None
    assert done.error is None


async def test_browser_mode_propagates_to_job(monkeypatch) -> None:
    store = JobStore(settings=_settings())
    job = await store.create(
        ExtractRequest(url="https://example.com/", prompt="get it")
    )

    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        return _fetch_result(mode="browser")

    monkeypatch.setattr(fetch_service, "fetch", fake_fetch)
    monkeypatch.setattr(
        registry,
        "get_provider",
        lambda settings, *, override=None: _FakeProvider(result={"ok": True}),
    )

    await run_job(job.id, app_state=_app_state(store, _settings()))

    done = await store.get(job.id)
    assert done is not None
    assert done.mode == "browser"


async def test_fetch_error_marks_job_error_with_message(monkeypatch) -> None:
    store = JobStore(settings=_settings())
    job = await store.create(ExtractRequest(url="https://example.com/", prompt="p"))

    async def boom(url: str, **kwargs: Any) -> FetchResult:
        raise FetchError("upstream returned HTTP 404")

    monkeypatch.setattr(fetch_service, "fetch", boom)

    await run_job(job.id, app_state=_app_state(store, _settings()))

    errored = await store.get(job.id)
    assert errored is not None
    assert errored.status is JobStatus.error
    assert errored.error == "upstream returned HTTP 404"
    assert errored.result is None
    assert errored.finished_at is not None


async def test_ssrf_error_subclass_is_caught(monkeypatch) -> None:
    store = JobStore(settings=_settings())
    job = await store.create(ExtractRequest(url="https://example.com/", prompt="p"))

    async def boom(url: str, **kwargs: Any) -> FetchResult:
        raise SSRFError("blocked private address")

    monkeypatch.setattr(fetch_service, "fetch", boom)

    await run_job(job.id, app_state=_app_state(store, _settings()))

    errored = await store.get(job.id)
    assert errored is not None
    assert errored.status is JobStatus.error
    assert errored.error == "blocked private address"


async def test_provider_error_from_registry_marks_error(monkeypatch) -> None:
    store = JobStore(settings=_settings())
    job = await store.create(ExtractRequest(url="https://example.com/", prompt="p"))

    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        return _fetch_result()

    monkeypatch.setattr(fetch_service, "fetch", fake_fetch)

    def boom(settings, *, override=None):
        raise ProviderError("provider 'openai' not available")

    monkeypatch.setattr(registry, "get_provider", boom)

    await run_job(job.id, app_state=_app_state(store, _settings()))

    errored = await store.get(job.id)
    assert errored is not None
    assert errored.status is JobStatus.error
    assert errored.error == "provider 'openai' not available"


async def test_schema_mismatch_marks_error_via_engine(monkeypatch) -> None:
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    store = JobStore(settings=_settings())
    job = await store.create(
        ExtractRequest(url="https://example.com/", prompt="p", output_schema=schema)
    )

    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        return _fetch_result()

    monkeypatch.setattr(fetch_service, "fetch", fake_fetch)
    # `name` must be a string; an int violates the original schema -> ProviderError.
    monkeypatch.setattr(
        registry,
        "get_provider",
        lambda settings, *, override=None: _FakeProvider(result={"name": 123}),
    )

    await run_job(job.id, app_state=_app_state(store, _settings()))

    errored = await store.get(job.id)
    assert errored is not None
    assert errored.status is JobStatus.error
    assert errored.error is not None
    assert errored.error.startswith("extraction did not match schema:")


async def test_unknown_error_uses_generic_non_leaky_message(monkeypatch) -> None:
    store = JobStore(settings=_settings())
    job = await store.create(ExtractRequest(url="https://example.com/", prompt="p"))

    async def boom(url: str, **kwargs: Any) -> FetchResult:
        raise RuntimeError("secret /etc/passwd path leaked")

    monkeypatch.setattr(fetch_service, "fetch", boom)

    await run_job(job.id, app_state=_app_state(store, _settings()))

    errored = await store.get(job.id)
    assert errored is not None
    assert errored.status is JobStatus.error
    assert errored.error == "internal error — see server logs"
    assert "secret" not in errored.error


async def test_never_raises_on_already_terminal_job() -> None:
    store = JobStore(settings=_settings())
    job = await store.create(ExtractRequest(url="https://example.com/", prompt="p"))
    await store.mark_running(job.id)
    await store.mark_done(job.id, result={"x": 1}, mode="http")

    # mark_running now raises JobStateError; the guarded handler must swallow it.
    await run_job(job.id, app_state=_app_state(store, _settings()))

    final = await store.get(job.id)
    assert final is not None
    assert final.status is JobStatus.done  # original terminal state preserved
    assert final.result == {"x": 1}


async def test_never_raises_on_missing_job_id() -> None:
    store = JobStore(settings=_settings())
    # No exception should escape even though the id is unknown.
    await run_job("does-not-exist", app_state=_app_state(store, _settings()))
    assert await store.get("does-not-exist") is None


async def test_url_coerced_to_str_and_provider_override_forwarded(monkeypatch) -> None:
    store = JobStore(settings=_settings())
    job = await store.create(
        ExtractRequest(url="https://example.com/", prompt="p", provider="anthropic")
    )
    seen: dict[str, Any] = {}

    async def fake_fetch(url: str, **kwargs: Any) -> FetchResult:
        seen["url"] = url
        seen["url_type"] = type(url)
        return _fetch_result()

    monkeypatch.setattr(fetch_service, "fetch", fake_fetch)

    def fake_get_provider(settings, *, override=None):
        seen["override"] = override
        return _FakeProvider(result={"ok": True})

    monkeypatch.setattr(registry, "get_provider", fake_get_provider)

    await run_job(job.id, app_state=_app_state(store, _settings()))

    assert seen["url_type"] is str
    assert seen["url"] == "https://example.com/"
    assert seen["override"] == "anthropic"

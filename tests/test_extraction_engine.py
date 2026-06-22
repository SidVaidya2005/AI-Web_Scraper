"""Tests for app.extraction.engine (F12): the provider-injected orchestrator.

The engine selects no provider and reads no settings — a structural `FakeProvider`
is injected. Tests pin: the provider is handed the *normalized* schema, output is
validated against the *original* schema, a mismatch maps to a readable
`ProviderError`, a no-schema call skips validation, a provider `ProviderError`
propagates unchanged, and the caller's schema dict is never mutated.
"""

import copy
from typing import Any

import pytest

from app.extraction.engine import extract
from app.providers.base import ProviderError

# A simple, in-subset schema: one string property, no additionalProperties/required.
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
}


class FakeProvider:
    """Structural `LLMProvider`: records the json_schema it received, returns/raises."""

    def __init__(
        self, *, result: dict[str, Any] | None = None, error: Exception | None = None
    ) -> None:
        self._result = result
        self._error = error
        self.received_json_schema: dict[str, Any] | None = None
        self.received_content: str | None = None
        self.received_prompt: str | None = None
        self.calls = 0

    async def extract(
        self, *, content: str, prompt: str, json_schema: dict[str, Any] | None
    ) -> dict[str, Any]:
        self.calls += 1
        self.received_content = content
        self.received_prompt = prompt
        self.received_json_schema = json_schema
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


async def test_happy_path_returns_result_and_provider_gets_normalized_schema() -> None:
    provider = FakeProvider(result={"name": "widget"})
    out = await extract(
        "page text", prompt="get the name", schema=_SCHEMA, provider=provider
    )
    assert out == {"name": "widget"}
    # The provider is handed the STRICT-normalized schema, not the original.
    normalized = provider.received_json_schema
    assert normalized is not None
    assert normalized["additionalProperties"] is False
    assert normalized["required"] == ["name"]
    # content + prompt are passed straight through (no engine-side framing).
    assert provider.received_content == "page text"
    assert provider.received_prompt == "get the name"


async def test_validates_against_original_not_normalized_schema() -> None:
    # An extra key would fail the normalized (additionalProperties:false) schema, but
    # the engine validates against the ORIGINAL (which permits it) — so this passes.
    provider = FakeProvider(result={"name": "x", "extra": 1})
    out = await extract("c", prompt="p", schema=_SCHEMA, provider=provider)
    assert out == {"name": "x", "extra": 1}


async def test_schema_mismatch_raises_readable_provider_error() -> None:
    # `name` must be a string; an integer violates the original schema.
    provider = FakeProvider(result={"name": 123})
    with pytest.raises(ProviderError) as exc_info:
        await extract("c", prompt="p", schema=_SCHEMA, provider=provider)
    assert str(exc_info.value).startswith("extraction did not match schema:")


async def test_no_schema_skips_validation_and_returns_verbatim() -> None:
    # With schema=None the provider gets json_schema=None and the result is returned
    # untouched — even a shape that would fail _SCHEMA.
    provider = FakeProvider(result={"anything": [1, 2, 3]})
    out = await extract("c", prompt="p", schema=None, provider=provider)
    assert out == {"anything": [1, 2, 3]}
    assert provider.received_json_schema is None


async def test_provider_error_propagates_unchanged() -> None:
    boom = ProviderError("LLM provider request failed")
    provider = FakeProvider(error=boom)
    with pytest.raises(ProviderError) as exc_info:
        await extract("c", prompt="p", schema=_SCHEMA, provider=provider)
    # Not caught or rewrapped by the engine — the runner is the boundary.
    assert exc_info.value is boom


async def test_original_schema_not_mutated() -> None:
    before = copy.deepcopy(_SCHEMA)
    provider = FakeProvider(result={"name": "ok"})
    await extract("c", prompt="p", schema=_SCHEMA, provider=provider)
    assert _SCHEMA == before  # normalize_for_strict deep-copies; original is untouched

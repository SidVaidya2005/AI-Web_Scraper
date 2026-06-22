"""Tests for app.providers: the base contract (F09) + Anthropic provider/registry (F10).

F09 (interface): a structurally-conforming fake proves the @runtime_checkable
Protocol accepts it (isinstance) and that `extract` awaits to a dict; a non-conformer
proves the runtime check discriminates.

F10 (Anthropic + registry): the SDK is fully mocked via an injected fake client
(no live LLM call). Tests assert the forced-tool call shape, strict-iff-schema,
the untrusted-content framing, generic error mapping, and registry selection.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.config import Settings
from app.providers.anthropic_provider import _SYSTEM, _TOOL_NAME, AnthropicProvider
from app.providers.base import LLMProvider, ProviderError
from app.providers.registry import get_provider


class FakeProvider:
    """Minimal structural match for LLMProvider — returns a fixed object envelope."""

    async def extract(
        self, *, content: str, prompt: str, json_schema: dict[str, Any] | None
    ) -> dict[str, Any]:
        return {"ok": True, "content": content, "prompt": prompt}


def test_fake_provider_satisfies_protocol() -> None:
    assert isinstance(FakeProvider(), LLMProvider)


def test_non_conforming_object_is_not_a_provider() -> None:
    # An object without `extract` must fail the runtime check — proves it discriminates.
    assert not isinstance(object(), LLMProvider)


async def test_extract_is_awaitable_and_returns_dict() -> None:
    result = await FakeProvider().extract(content="x", prompt="p", json_schema=None)
    assert isinstance(result, dict)
    assert result["ok"] is True


def test_provider_error_is_runtimeerror() -> None:
    assert issubclass(ProviderError, RuntimeError)
    try:
        raise ProviderError("provider boom")
    except ProviderError as exc:
        assert str(exc) == "provider boom"


# --- F10: Anthropic provider (SDK mocked via injected client) ---


@dataclass
class _Block:
    """Stand-in for an Anthropic content block (tool_use or text)."""

    type: str
    name: str | None = None
    input: dict[str, Any] | None = None


@dataclass
class _Message:
    """Stand-in for the Messages API response object."""

    content: list[_Block]


class _FakeMessages:
    def __init__(self, *, result: _Message | None, error: Exception | None) -> None:
        self._result = result
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _Message:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


@dataclass
class _FakeClient:
    result: _Message | None = None
    error: Exception | None = None
    messages: _FakeMessages = field(init=False)

    def __post_init__(self) -> None:
        self.messages = _FakeMessages(result=self.result, error=self.error)


def _provider(
    *,
    result: _Message | None = None,
    error: Exception | None = None,
    model: str = "claude-sonnet-4-6",
) -> AnthropicProvider:
    return AnthropicProvider(
        api_key="test-key",
        model=model,
        timeout=60,
        client=_FakeClient(result=result, error=error),
    )


async def test_extract_returns_tool_input_dict() -> None:
    provider = _provider(
        result=_Message([_Block("tool_use", _TOOL_NAME, {"items": [1, 2]})])
    )
    out = await provider.extract(content="page", prompt="get items", json_schema=None)
    assert out == {"items": [1, 2]}


async def test_strict_set_and_schema_passed_through_unchanged() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    provider = _provider(result=_Message([_Block("tool_use", _TOOL_NAME, {"x": "y"})]))
    await provider.extract(content="c", prompt="p", json_schema=schema)
    tool = provider._client.messages.calls[0]["tools"][0]
    assert tool["strict"] is True
    # Passed through as-is — no normalization in the provider (that is F11's job).
    assert tool["input_schema"] == schema


async def test_strict_absent_when_no_schema() -> None:
    provider = _provider(result=_Message([_Block("tool_use", _TOOL_NAME, {"a": 1})]))
    await provider.extract(content="c", prompt="p", json_schema=None)
    tool = provider._client.messages.calls[0]["tools"][0]
    assert "strict" not in tool
    assert tool["input_schema"] == {"type": "object", "additionalProperties": True}


async def test_call_carries_system_delimiter_model_and_forced_tool() -> None:
    provider = _provider(
        result=_Message([_Block("tool_use", _TOOL_NAME, {"a": 1})]),
        model="claude-opus-4-8",
    )
    await provider.extract(
        content="PAGEBODY", prompt="extract things", json_schema=None
    )
    call = provider._client.messages.calls[0]
    assert call["model"] == "claude-opus-4-8"  # forwarded, never hardcoded
    assert call["system"] == _SYSTEM
    assert call["tool_choice"] == {"type": "tool", "name": _TOOL_NAME}
    user_content = call["messages"][0]["content"]
    assert "<page_content>\nPAGEBODY\n</page_content>" in user_content
    assert "extract things" in user_content


async def test_sdk_error_maps_to_generic_provider_error() -> None:
    provider = _provider(error=RuntimeError("secret /path/to/key leaked"))
    with pytest.raises(ProviderError) as exc_info:
        await provider.extract(content="c", prompt="p", json_schema=None)
    # Generic, user-safe message — the raw error never leaks into it.
    assert str(exc_info.value) == "LLM provider request failed"
    assert "secret" not in str(exc_info.value)


async def test_no_tool_use_block_raises_provider_error() -> None:
    provider = _provider(result=_Message([_Block("text")]))
    with pytest.raises(ProviderError):
        await provider.extract(content="c", prompt="p", json_schema=None)


# --- F10: registry selection ---


def _settings(**overrides: Any) -> Settings:
    # Pin the key so the dev shell can't bleed in; init kwargs outrank env in
    # pydantic-settings, so an explicit value is authoritative.
    overrides.setdefault("anthropic_api_key", "test-key")
    return Settings(_env_file=None, **overrides)


def test_registry_returns_anthropic_provider() -> None:
    settings = _settings()
    provider = get_provider(settings)
    assert isinstance(provider, LLMProvider)
    assert isinstance(provider, AnthropicProvider)
    # Model sourced from settings, not a literal.
    assert provider._model == settings.anthropic_model


def test_registry_override_outranks_config() -> None:
    # Config says anthropic, but the per-request override asks for openai (F22).
    with pytest.raises(ProviderError):
        get_provider(_settings(), override="openai")


def test_registry_openai_config_not_available() -> None:
    with pytest.raises(ProviderError):
        get_provider(_settings(llm_provider="openai"))


def test_registry_unknown_provider_raises() -> None:
    with pytest.raises(ProviderError):
        get_provider(_settings(), override="banana")


def test_registry_missing_key_raises() -> None:
    with pytest.raises(ProviderError) as exc_info:
        get_provider(_settings(anthropic_api_key=""))
    assert "ANTHROPIC_API_KEY" in str(exc_info.value)

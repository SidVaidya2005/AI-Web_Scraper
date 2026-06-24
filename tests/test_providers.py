"""Tests for app.providers: base contract (F09), Anthropic (F10), OpenAI (F22).

F09 (interface): a structurally-conforming fake proves the @runtime_checkable
Protocol accepts it (isinstance) and that `extract` awaits to a dict; a non-conformer
proves the runtime check discriminates.

F10 (Anthropic) / F22 (OpenAI): each SDK is fully mocked via an injected fake client
(no live LLM call). Tests assert the forced-tool/function call shape, strict-iff-schema,
the shared untrusted-content framing, generic error mapping, and registry selection.
OpenAI additionally proves its JSON-string arguments parse into the object envelope.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.config import Settings
from app.providers._prompts import SYSTEM_PROMPT, TOOL_NAME
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMProvider, ProviderError
from app.providers.openai_provider import OpenAIProvider
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
        result=_Message([_Block("tool_use", TOOL_NAME, {"items": [1, 2]})])
    )
    out = await provider.extract(content="page", prompt="get items", json_schema=None)
    assert out == {"items": [1, 2]}


async def test_strict_set_and_schema_passed_through_unchanged() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    provider = _provider(result=_Message([_Block("tool_use", TOOL_NAME, {"x": "y"})]))
    await provider.extract(content="c", prompt="p", json_schema=schema)
    tool = provider._client.messages.calls[0]["tools"][0]
    assert tool["strict"] is True
    # Passed through as-is — no normalization in the provider (that is F11's job).
    assert tool["input_schema"] == schema


async def test_strict_absent_when_no_schema() -> None:
    provider = _provider(result=_Message([_Block("tool_use", TOOL_NAME, {"a": 1})]))
    await provider.extract(content="c", prompt="p", json_schema=None)
    tool = provider._client.messages.calls[0]["tools"][0]
    assert "strict" not in tool
    assert tool["input_schema"] == {"type": "object", "additionalProperties": True}


async def test_call_carries_system_delimiter_model_and_forced_tool() -> None:
    provider = _provider(
        result=_Message([_Block("tool_use", TOOL_NAME, {"a": 1})]),
        model="claude-opus-4-8",
    )
    await provider.extract(
        content="PAGEBODY", prompt="extract things", json_schema=None
    )
    call = provider._client.messages.calls[0]
    assert call["model"] == "claude-opus-4-8"  # forwarded, never hardcoded
    assert call["system"] == SYSTEM_PROMPT
    assert call["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
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
    # Config says anthropic (default), but the per-request override asks for openai:
    # the override must win and route to the OpenAI branch (F22).
    settings = _settings(openai_api_key="ok-key", openai_model="gpt-test")
    provider = get_provider(settings, override="openai")
    assert isinstance(provider, OpenAIProvider)
    assert provider._model == "gpt-test"


def test_registry_selects_openai_from_config() -> None:
    settings = _settings(
        llm_provider="openai", openai_api_key="ok-key", openai_model="gpt-test"
    )
    provider = get_provider(settings)
    assert isinstance(provider, LLMProvider)
    assert isinstance(provider, OpenAIProvider)
    assert provider._model == settings.openai_model  # from settings, not a literal


def test_registry_openai_missing_key_raises() -> None:
    with pytest.raises(ProviderError) as exc_info:
        get_provider(_settings(llm_provider="openai", openai_model="gpt-test"))
    assert "OPENAI_API_KEY" in str(exc_info.value)


def test_registry_openai_missing_model_raises() -> None:
    # OpenAI has no default model id — an empty model must fail fast, not at call time.
    with pytest.raises(ProviderError) as exc_info:
        get_provider(_settings(llm_provider="openai", openai_api_key="ok-key"))
    assert "OPENAI_MODEL" in str(exc_info.value)


def test_registry_unknown_provider_raises() -> None:
    with pytest.raises(ProviderError):
        get_provider(_settings(), override="banana")


def test_registry_missing_key_raises() -> None:
    with pytest.raises(ProviderError) as exc_info:
        get_provider(_settings(anthropic_api_key=""))
    assert "ANTHROPIC_API_KEY" in str(exc_info.value)


# --- F22: OpenAI provider (SDK mocked via injected Chat Completions client) ---


@dataclass
class _Function:
    """Stand-in for an OpenAI tool_call.function — `arguments` is a JSON *string*."""

    name: str
    arguments: str


@dataclass
class _ToolCall:
    function: _Function


@dataclass
class _ChatMessage:
    tool_calls: list[_ToolCall] | None


@dataclass
class _Choice:
    message: _ChatMessage


@dataclass
class _Completion:
    """Stand-in for the Chat Completions response object."""

    choices: list[_Choice]


class _FakeChatCompletions:
    def __init__(self, *, result: _Completion | None, error: Exception | None) -> None:
        self._result = result
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _Completion:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class _FakeChat:
    def __init__(self, completions: _FakeChatCompletions) -> None:
        self.completions = completions


@dataclass
class _FakeOpenAIClient:
    result: _Completion | None = None
    error: Exception | None = None
    chat: _FakeChat = field(init=False)

    def __post_init__(self) -> None:
        self.chat = _FakeChat(
            _FakeChatCompletions(result=self.result, error=self.error)
        )


def _completion(arguments: str, *, name: str = TOOL_NAME) -> _Completion:
    """A response carrying one forced tool call with `arguments` as a JSON string."""
    return _Completion([_Choice(_ChatMessage([_ToolCall(_Function(name, arguments))]))])


def _openai_provider(
    *,
    result: _Completion | None = None,
    error: Exception | None = None,
    model: str = "gpt-test",
) -> OpenAIProvider:
    return OpenAIProvider(
        api_key="test-key",
        model=model,
        timeout=60,
        client=_FakeOpenAIClient(result=result, error=error),
    )


async def test_openai_parses_json_string_arguments_into_dict() -> None:
    # The key divergence from Anthropic: arguments arrive as a JSON string.
    provider = _openai_provider(result=_completion('{"items": [1, 2]}'))
    out = await provider.extract(content="page", prompt="get items", json_schema=None)
    assert out == {"items": [1, 2]}


async def test_openai_strict_set_and_schema_passed_as_parameters() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    provider = _openai_provider(result=_completion('{"x": "y"}'))
    await provider.extract(content="c", prompt="p", json_schema=schema)
    function = provider._client.chat.completions.calls[0]["tools"][0]["function"]
    assert function["strict"] is True
    assert function["parameters"] == schema  # passed through as-is


async def test_openai_strict_absent_when_no_schema() -> None:
    provider = _openai_provider(result=_completion('{"a": 1}'))
    await provider.extract(content="c", prompt="p", json_schema=None)
    function = provider._client.chat.completions.calls[0]["tools"][0]["function"]
    assert "strict" not in function
    assert function["parameters"] == {"type": "object", "additionalProperties": True}


async def test_openai_call_carries_system_delimiter_model_and_forced_function() -> None:
    provider = _openai_provider(result=_completion('{"a": 1}'), model="gpt-9000")
    await provider.extract(
        content="PAGEBODY", prompt="extract things", json_schema=None
    )
    call = provider._client.chat.completions.calls[0]
    assert call["model"] == "gpt-9000"  # forwarded, never hardcoded
    assert call["tool_choice"] == {"type": "function", "function": {"name": TOOL_NAME}}
    assert call["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    user_content = call["messages"][1]["content"]
    assert "<page_content>\nPAGEBODY\n</page_content>" in user_content
    assert "extract things" in user_content


async def test_openai_sdk_error_maps_to_generic_provider_error() -> None:
    provider = _openai_provider(error=RuntimeError("secret /path/to/key leaked"))
    with pytest.raises(ProviderError) as exc_info:
        await provider.extract(content="c", prompt="p", json_schema=None)
    assert str(exc_info.value) == "LLM provider request failed"
    assert "secret" not in str(exc_info.value)


async def test_openai_no_tool_call_raises_provider_error() -> None:
    provider = _openai_provider(result=_Completion([_Choice(_ChatMessage(None))]))
    with pytest.raises(ProviderError):
        await provider.extract(content="c", prompt="p", json_schema=None)


async def test_openai_unparseable_arguments_raises_provider_error() -> None:
    provider = _openai_provider(result=_completion("{not valid json"))
    with pytest.raises(ProviderError):
        await provider.extract(content="c", prompt="p", json_schema=None)


async def test_openai_non_object_arguments_raises_provider_error() -> None:
    # Valid JSON but a top-level list is not the object envelope contract.
    provider = _openai_provider(result=_completion("[1, 2]"))
    with pytest.raises(ProviderError):
        await provider.extract(content="c", prompt="p", json_schema=None)

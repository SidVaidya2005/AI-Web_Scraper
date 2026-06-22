"""Tests for the app.providers.base contract: LLMProvider Protocol + ProviderError.

Pure interface feature — no SDK, no network. A structurally-conforming fake proves
the @runtime_checkable Protocol accepts it (isinstance) and that `extract` awaits to a
dict; a non-conforming object proves the runtime check actually discriminates.
"""

from typing import Any

from app.providers.base import LLMProvider, ProviderError


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

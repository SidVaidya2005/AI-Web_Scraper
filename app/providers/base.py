"""The provider-agnostic LLM contract and its uniform error type.

Every concrete provider (Anthropic, OpenAI, test fakes) implements `LLMProvider` so
that callers in `app/extraction/` talk to one shape and never import an SDK directly.
"""

from typing import Any, Protocol, runtime_checkable


class ProviderError(RuntimeError):
    """Raised when an LLM provider call fails or returns unusable output."""


@runtime_checkable
class LLMProvider(Protocol):
    async def extract(
        self,
        *,
        content: str,
        prompt: str,
        json_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Return structured data extracted from untrusted `content` per `prompt`.

        Always returns a JSON object envelope (lists/scalars under a key); raises
        `ProviderError` on a failed call or unusable output.
        """
        ...

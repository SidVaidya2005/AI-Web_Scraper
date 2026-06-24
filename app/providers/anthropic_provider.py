"""Anthropic LLM provider: structured extraction via forced tool use."""

import logging
from typing import Any

from anthropic import AsyncAnthropic

from app.providers._prompts import SYSTEM_PROMPT, TOOL_NAME, build_user_message
from app.providers.base import ProviderError

logger = logging.getLogger("app.providers")

_MAX_TOKENS = 4096  # required by the API; project default


class AnthropicProvider:
    """Extract structured data with Anthropic via a single forced tool call.

    Returns the tool call's `input` as a JSON object envelope; raises
    `ProviderError` (generic, user-safe message) on any SDK/network failure or
    when the model returns no usable tool call.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float,
        client: AsyncAnthropic | None = None,
    ) -> None:
        # `client` is an injection seam for tests; production builds a real one.
        self._client = client or AsyncAnthropic(api_key=api_key, timeout=timeout)
        self._model = model

    async def extract(
        self, *, content: str, prompt: str, json_schema: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Return structured data from `content` per `prompt`/`json_schema`."""
        tool: dict[str, Any] = {
            "name": TOOL_NAME,
            "description": prompt,
            "input_schema": json_schema
            or {"type": "object", "additionalProperties": True},
        }
        if json_schema is not None:
            # Conform args to the schema where the subset allows. The schema is
            # passed through as-is; strict-mode normalization is owned by the
            # extraction layer (F11), applied before this provider is called.
            tool["strict"] = True
        try:
            msg = await self._client.messages.create(
                model=self._model,  # always from settings, never a literal
                max_tokens=_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=[tool],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=[
                    {"role": "user", "content": build_user_message(prompt, content)}
                ],
            )
        except Exception as exc:  # SDK/network errors → uniform, user-SAFE error
            logger.exception("anthropic call failed")  # full detail to logs only
            raise ProviderError("LLM provider request failed") from exc

        for block in msg.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                return dict(block.input)
        raise ProviderError("LLM provider returned no extraction")

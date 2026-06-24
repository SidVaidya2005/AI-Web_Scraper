"""OpenAI LLM provider: structured extraction via forced function calling.

Mirrors the Anthropic provider's forced-tool + strict contract and object-envelope
return, so callers in `app/extraction/` never care which provider ran. The one real
divergence: OpenAI's Chat Completions returns tool-call `arguments` as a JSON *string*,
so it is `json.loads`'d (Anthropic's `block.input` is already a parsed dict).
"""

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.providers._prompts import SYSTEM_PROMPT, TOOL_NAME, build_user_message
from app.providers.base import ProviderError

logger = logging.getLogger("app.providers")

_MAX_TOKENS = 4096  # cap on generated tokens; project default


class OpenAIProvider:
    """Extract structured data with OpenAI via a single forced function call.

    Forces the `emit_extraction` function (with `strict` when a schema is supplied),
    parses the returned JSON-string arguments into an object envelope, and raises
    `ProviderError` (generic, user-safe message) on any SDK/network failure or when
    the model returns no usable / unparseable tool call.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float,
        client: AsyncOpenAI | None = None,
    ) -> None:
        # `client` is an injection seam for tests; production builds a real one.
        self._client = client or AsyncOpenAI(api_key=api_key, timeout=timeout)
        self._model = model

    async def extract(
        self, *, content: str, prompt: str, json_schema: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Return structured data from `content` per `prompt`/`json_schema`."""
        function: dict[str, Any] = {
            "name": TOOL_NAME,
            "description": prompt,
            "parameters": json_schema
            or {"type": "object", "additionalProperties": True},
        }
        if json_schema is not None:
            # Strict adherence where the (already-normalized) schema allows;
            # normalization is owned by the extraction layer (F11).
            function["strict"] = True
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,  # always from settings, never a literal
                max_completion_tokens=_MAX_TOKENS,
                tools=[{"type": "function", "function": function}],
                tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_message(prompt, content)},
                ],
            )
        except Exception as exc:  # SDK/network errors → uniform, user-SAFE error
            logger.exception("openai call failed")  # full detail to logs only
            raise ProviderError("LLM provider request failed") from exc

        for choice in resp.choices:
            for call in choice.message.tool_calls or []:
                if call.function.name != TOOL_NAME:
                    continue
                try:
                    data = json.loads(call.function.arguments)
                except (json.JSONDecodeError, TypeError) as exc:
                    raise ProviderError(
                        "LLM provider returned unparseable extraction"
                    ) from exc
                if not isinstance(data, dict):
                    raise ProviderError("LLM provider returned a non-object extraction")
                return data
        raise ProviderError("LLM provider returned no extraction")

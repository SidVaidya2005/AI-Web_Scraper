"""Orchestrate cleaned content + prompt/schema into a validated structured result.

The thin layer between the job runner and an LLM provider: normalize the request
schema for the provider's strict tool, call the injected provider, and validate the
returned dict against the user's *original* schema. Selects no provider and reads no
settings — the runner injects a ready `LLMProvider`; provider/registry errors
propagate to the runner, the top-level error boundary.
"""

from typing import Any

from jsonschema.exceptions import ValidationError

from app.extraction.schemas import normalize_for_strict, validate_output
from app.providers.base import LLMProvider, ProviderError


async def extract(
    content: str,
    *,
    prompt: str,
    schema: dict[str, Any] | None,
    provider: LLMProvider,
) -> dict[str, Any]:
    """Return structured data for `content` per `prompt`, validated against `schema`.

    The provider receives `normalize_for_strict(schema)` (strict-tool input); the
    result is validated against the original `schema` when one is supplied. A schema
    mismatch raises `ProviderError`; a `ProviderError` from the provider propagates
    unchanged. Always returns a JSON object envelope.
    """
    json_schema = normalize_for_strict(schema) if schema is not None else None
    raw = await provider.extract(
        content=content, prompt=prompt, json_schema=json_schema
    )
    if schema is not None:
        try:
            validate_output(raw, schema=schema)
        except ValidationError as exc:
            # exc.message is user-readable; never surface the full exception object.
            raise ProviderError(
                f"extraction did not match schema: {exc.message}"
            ) from exc
    return raw

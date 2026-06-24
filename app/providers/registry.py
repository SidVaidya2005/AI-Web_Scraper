"""Select an LLMProvider from config (with an optional per-request override)."""

from app.config import Settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMProvider, ProviderError
from app.providers.openai_provider import OpenAIProvider


def get_provider(settings: Settings, *, override: str | None = None) -> LLMProvider:
    """Return the provider named by `override` or `settings.llm_provider`.

    Raises `ProviderError` for an unknown provider, or when the selected provider's
    API key (or model, for OpenAI which has no default) is not configured.
    """
    name = override or settings.llm_provider
    if name == "anthropic":
        key = settings.anthropic_api_key.get_secret_value()
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY not configured")
        return AnthropicProvider(
            api_key=key,
            model=settings.anthropic_model,
            timeout=settings.llm_timeout_seconds,
        )
    if name == "openai":
        key = settings.openai_api_key.get_secret_value()
        if not key:
            raise ProviderError("OPENAI_API_KEY not configured")
        if not settings.openai_model:  # no default model id — must be set explicitly
            raise ProviderError("OPENAI_MODEL not configured")
        return OpenAIProvider(
            api_key=key,
            model=settings.openai_model,
            timeout=settings.llm_timeout_seconds,
        )
    raise ProviderError(f"provider {name!r} not available")

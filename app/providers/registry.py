"""Select an LLMProvider from config (with an optional per-request override)."""

from app.config import Settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMProvider, ProviderError


def get_provider(settings: Settings, *, override: str | None = None) -> LLMProvider:
    """Return the provider named by `override` or `settings.llm_provider`.

    Raises `ProviderError` for an unimplemented/unknown provider, or when the
    selected provider's API key is not configured.
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
    # OpenAI lands in F22; any other name is unknown.
    raise ProviderError(f"provider {name!r} not available")

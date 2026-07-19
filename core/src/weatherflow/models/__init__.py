"""Provider adapters for WeatherFlow's provider-neutral model protocol."""

from weatherflow.models.anthropic import (
    AnthropicAuthenticationError,
    AnthropicError,
    AnthropicMessagesAdapter,
    AnthropicResponseError,
    AnthropicRetryableError,
)
from weatherflow.models.configuration import (
    ModelConfiguration,
    ModelConfigurationRepository,
    ModelConfigurationService,
    ModelProvider,
    ModelStatus,
    ProviderModel,
    ProviderModelCatalog,
    ProviderPreset,
    RunModelRoute,
    RunModelRouteRepository,
    normalize_model_base_url,
    provider_presets,
)
from weatherflow.models.errors import ModelResponseFailureStage
from weatherflow.models.minimax import (
    MiniMaxAdapter,
    MiniMaxAuthenticationError,
    MiniMaxError,
    MiniMaxResponseError,
    MiniMaxRetryableError,
    OpenAICompatibleAdapter,
)
from weatherflow.models.openai import (
    OpenAIAuthenticationError,
    OpenAIError,
    OpenAIResponseError,
    OpenAIResponsesAdapter,
    OpenAIRetryableError,
)

__all__ = [
    "MiniMaxAdapter",
    "MiniMaxAuthenticationError",
    "MiniMaxError",
    "MiniMaxResponseError",
    "MiniMaxRetryableError",
    "OpenAICompatibleAdapter",
    "OpenAIResponsesAdapter",
    "OpenAIError",
    "OpenAIAuthenticationError",
    "OpenAIResponseError",
    "OpenAIRetryableError",
    "AnthropicMessagesAdapter",
    "AnthropicError",
    "AnthropicAuthenticationError",
    "AnthropicResponseError",
    "AnthropicRetryableError",
    "ModelConfiguration",
    "ModelResponseFailureStage",
    "ModelConfigurationRepository",
    "ModelConfigurationService",
    "ModelProvider",
    "ModelStatus",
    "ProviderModelCatalog",
    "ProviderModel",
    "ProviderPreset",
    "RunModelRoute",
    "RunModelRouteRepository",
    "normalize_model_base_url",
    "provider_presets",
]

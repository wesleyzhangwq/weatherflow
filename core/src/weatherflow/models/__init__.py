"""Provider adapters for WeatherFlow's provider-neutral model protocol."""

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
    provider_presets,
)
from weatherflow.models.minimax import (
    MiniMaxAdapter,
    MiniMaxAuthenticationError,
    MiniMaxError,
    MiniMaxResponseError,
    MiniMaxRetryableError,
    OpenAICompatibleAdapter,
)

__all__ = [
    "MiniMaxAdapter",
    "MiniMaxAuthenticationError",
    "MiniMaxError",
    "MiniMaxResponseError",
    "MiniMaxRetryableError",
    "OpenAICompatibleAdapter",
    "ModelConfiguration",
    "ModelConfigurationRepository",
    "ModelConfigurationService",
    "ModelProvider",
    "ModelStatus",
    "ProviderModelCatalog",
    "ProviderModel",
    "ProviderPreset",
    "RunModelRoute",
    "RunModelRouteRepository",
    "provider_presets",
]

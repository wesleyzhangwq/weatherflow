"""Provider adapters for WeatherFlow's provider-neutral model protocol."""

from weatherflow.models.configuration import (
    ModelConfiguration,
    ModelConfigurationRepository,
    ModelConfigurationService,
    ModelProvider,
    ModelStatus,
)
from weatherflow.models.minimax import (
    MiniMaxAdapter,
    MiniMaxAuthenticationError,
    MiniMaxError,
    MiniMaxResponseError,
    MiniMaxRetryableError,
)

__all__ = [
    "MiniMaxAdapter",
    "MiniMaxAuthenticationError",
    "MiniMaxError",
    "MiniMaxResponseError",
    "MiniMaxRetryableError",
    "ModelConfiguration",
    "ModelConfigurationRepository",
    "ModelConfigurationService",
    "ModelProvider",
    "ModelStatus",
]

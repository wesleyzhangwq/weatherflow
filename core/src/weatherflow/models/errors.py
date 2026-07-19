from enum import StrEnum


class ModelResponseFailureStage(StrEnum):
    """Bounded, content-free location of a rejected model response."""

    HTTP_RESPONSE = "http_response"
    PROVIDER_STATUS = "provider_status"
    CHOICE = "choice"
    MESSAGE = "message"
    EMPTY_TEXT = "empty_text"
    MODEL_OUTPUT = "model_output"
    UNKNOWN = "unknown"

from enum import StrEnum
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolEffect(StrEnum):
    OBSERVE = "observe"
    WORKSPACE_WRITE = "workspace_write"
    EXECUTE = "execute"
    NETWORK_READ = "network_read"
    EXTERNAL_WRITE = "external_write"
    INSTALL = "install"
    DESTRUCTIVE = "destructive"
    SENSITIVE = "sensitive"


class IdempotencyKind(StrEnum):
    NONE = "none"
    KEY = "key"
    STATUS_CHECK = "status_check"


class ToolHealth(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ToolSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    effect: ToolEffect
    required_scopes: frozenset[str] = frozenset()
    idempotency: IdempotencyKind = IdempotencyKind.NONE
    timeout_seconds: int = Field(default=30, ge=1)
    source: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    health: ToolHealth = ToolHealth.AVAILABLE

    @field_validator("input_schema", "output_schema")
    @classmethod
    def require_valid_draft_2020_12_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            Draft202012Validator.check_schema(value)
        except SchemaError as error:
            raise ValueError("tool schema must be valid JSON Schema Draft 2020-12") from error
        return value

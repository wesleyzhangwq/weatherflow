from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for


@dataclass(frozen=True)
class ToolArgumentValidation:
    valid: bool
    schema_valid: bool
    errors: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ToolOutputValidation:
    valid: bool
    schema_valid: bool
    errors: tuple[dict[str, Any], ...] = ()


def validate_tool_arguments(
    schema: dict[str, Any],
    arguments: dict[str, Any],
) -> ToolArgumentValidation:
    """Validate a tool call without echoing argument values into observations."""

    validator_type = validator_for(schema)
    try:
        validator_type.check_schema(schema)
    except SchemaError as error:
        return ToolArgumentValidation(
            valid=False,
            schema_valid=False,
            errors=(
                {
                    "keyword": "schema",
                    "path": _json_path(error.absolute_path),
                    "message": "the frozen tool input schema is invalid",
                },
            ),
        )

    validator = validator_type(schema, format_checker=FormatChecker())
    failures = sorted(validator.iter_errors(arguments), key=_error_sort_key)
    if not failures:
        return ToolArgumentValidation(valid=True, schema_valid=True)
    return ToolArgumentValidation(
        valid=False,
        schema_valid=True,
        errors=tuple(_safe_error(error) for error in failures),
    )


def validate_tool_output(
    schema: dict[str, Any],
    output: dict[str, Any],
) -> ToolOutputValidation:
    """Validate executor output without copying output values into diagnostics."""

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        return ToolOutputValidation(
            valid=False,
            schema_valid=False,
            errors=(
                {
                    "keyword": "schema",
                    "path": "$",
                    "message": "the frozen tool output schema is invalid",
                },
            ),
        )

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    failures = sorted(validator.iter_errors(output), key=_error_sort_key)
    if not failures:
        return ToolOutputValidation(valid=True, schema_valid=True)
    return ToolOutputValidation(
        valid=False,
        schema_valid=True,
        errors=tuple(_safe_output_error(error) for error in failures),
    )


def _error_sort_key(error: ValidationError) -> tuple[str, str]:
    return (_json_path(error.absolute_path), str(error.validator))


def _json_path(path: Any) -> str:
    segments = tuple(path)
    if not segments:
        return "$"
    rendered = "$"
    for segment in segments:
        if isinstance(segment, int):
            rendered += f"[{segment}]"
        else:
            rendered += f".{segment}"
    return rendered


def _safe_error(error: ValidationError) -> dict[str, Any]:
    keyword = str(error.validator)
    detail: dict[str, Any] = {
        "keyword": keyword,
        "path": _json_path(error.absolute_path),
        "message": f"value violates the {keyword} constraint",
    }
    if keyword == "required" and isinstance(error.instance, dict):
        required = set(error.validator_value or ())
        detail["missing"] = sorted(required - set(error.instance))
        detail["message"] = "required property is missing"
    elif keyword == "additionalProperties" and isinstance(error.instance, dict):
        properties = set((error.schema.get("properties") or {}).keys())
        detail["unexpected"] = sorted(set(error.instance) - properties)
        detail["message"] = "additional properties are not allowed"
    elif keyword == "type":
        detail["expected"] = error.validator_value
        detail["message"] = "value has the wrong JSON type"
    elif keyword == "enum":
        detail["allowed"] = error.validator_value
        detail["message"] = "value is not one of the allowed choices"
    return detail


def _safe_output_error(error: ValidationError) -> dict[str, Any]:
    """Describe a mismatch using only schema-derived data, never rejected output fields."""

    detail = _safe_error(error)
    detail.pop("unexpected", None)
    return detail

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

import httpx

from weatherflow.capabilities import ToolSpec
from weatherflow.continuations import (
    ProviderAssistantMessage,
    ProviderContinuationUnavailableError,
)
from weatherflow.extensions import (
    CredentialBroker,
    CredentialRef,
    CredentialUnavailableError,
)
from weatherflow.models.errors import ModelResponseFailureStage
from weatherflow.runtime import (
    DelegationTurn,
    FinalTurn,
    MessageRole,
    ModelCompletion,
    ModelRequest,
    ModelTurn,
    ModelUsage,
    ToolCallBatchTurn,
    ToolCallTurn,
)

DELEGATE_FUNCTION = "weatherflow_delegate"


class OpenAIError(ConnectionError):
    pass


class OpenAIRetryableError(OpenAIError):
    pass


class OpenAIAuthenticationError(OpenAIError):
    pass


class OpenAIResponseError(OpenAIError):
    def __init__(
        self,
        message: str,
        *,
        stage: ModelResponseFailureStage = ModelResponseFailureStage.UNKNOWN,
    ) -> None:
        super().__init__(message)
        self.stage = stage


class OpenAIResponsesAdapter:
    """Stateless OpenAI Responses API adapter for the provider-neutral turn loop."""

    continuation_provider = "openai"

    def __init__(
        self,
        *,
        broker: CredentialBroker,
        credential_ref: CredentialRef,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        max_output_tokens: int = 2048,
        timeout_seconds: float = 120,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if credential_ref.provider != "openai" or credential_ref.name != "api_key":
            raise ValueError("OpenAI adapter requires the fixed openai credential reference")
        if not model.strip() or len(model) > 200:
            raise ValueError("invalid OpenAI model identifier")
        normalized_url = base_url.rstrip("/")
        if not normalized_url.startswith("https://"):
            raise ValueError("model base URL must use HTTPS")
        if not 1 <= max_output_tokens <= 128_000:
            raise ValueError("max_output_tokens must be between 1 and 128000")
        self.broker = broker
        self.credential_ref = credential_ref
        self.model = model
        self.base_url = normalized_url
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self.client = client or httpx.AsyncClient()
        self.continuation_model = model
        self.pricing_catalog_version = None

    async def complete(self, request: ModelRequest) -> ModelTurn | ModelCompletion:
        name_to_tool = {_function_name(tool.tool_id): tool for tool in request.tools}
        tools = [_tool_payload(name, tool) for name, tool in name_to_tool.items()]
        if not request.tool_free and not request.agent.is_leaf:
            tools.append(_delegation_payload())
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": self._instructions(request),
            "input": self._input(request, name_to_tool),
            "max_output_tokens": self.max_output_tokens,
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = True

        async def transport(secret: str) -> dict[str, Any]:
            return await self._post("responses", secret, payload=payload)

        try:
            response = await self.broker.call(self.credential_ref, transport)
        except CredentialUnavailableError as error:
            raise OpenAIAuthenticationError("OpenAI credential is unavailable") from error
        return self._turn(response, name_to_tool)

    async def list_models(
        self,
        *,
        query: dict[str, str] | None = None,
    ) -> tuple[str, ...]:
        async def transport(secret: str) -> tuple[str, ...]:
            response = await self._get("models", secret, query=query)
            data = response.get("data")
            if not isinstance(data, list):
                raise OpenAIResponseError(
                    "OpenAI model catalog returned an invalid response",
                    stage=ModelResponseFailureStage.HTTP_RESPONSE,
                )
            models = tuple(
                item["id"]
                for item in data
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
            )
            if not models:
                raise OpenAIResponseError(
                    "OpenAI model catalog is empty",
                    stage=ModelResponseFailureStage.PROVIDER_STATUS,
                )
            return tuple(dict.fromkeys(models))

        try:
            return await self.broker.call(self.credential_ref, transport)
        except CredentialUnavailableError as error:
            raise OpenAIAuthenticationError("OpenAI credential is unavailable") from error

    async def verify(self) -> None:
        if self.model not in await self.list_models():
            raise OpenAIResponseError(
                "configured OpenAI model is not available",
                stage=ModelResponseFailureStage.PROVIDER_STATUS,
            )

    async def _post(
        self,
        path: str,
        secret: str,
        *,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = await self.client.post(
                f"{self.base_url}/{path}",
                headers={"Authorization": f"Bearer {secret}"},
                json=payload,
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise OpenAIRetryableError("OpenAI request is unavailable") from error
        return self._response(response)

    async def _get(
        self,
        path: str,
        secret: str,
        *,
        query: dict[str, str] | None,
    ) -> dict[str, Any]:
        try:
            response = await self.client.get(
                f"{self.base_url}/{path}",
                headers={"Authorization": f"Bearer {secret}"},
                params=query,
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise OpenAIRetryableError("OpenAI request is unavailable") from error
        return self._response(response)

    def _response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code in {401, 403}:
            raise OpenAIAuthenticationError("OpenAI credential was rejected")
        if response.status_code in {408, 409, 429} or response.status_code >= 500:
            raise OpenAIRetryableError(
                f"OpenAI request failed with retryable status {response.status_code}"
            )
        if response.is_error:
            raise OpenAIResponseError(
                f"OpenAI request failed with status {response.status_code}",
                stage=ModelResponseFailureStage.HTTP_RESPONSE,
            )
        try:
            value = response.json()
        except ValueError as error:
            raise OpenAIResponseError(
                "OpenAI returned invalid JSON",
                stage=ModelResponseFailureStage.HTTP_RESPONSE,
            ) from error
        if not isinstance(value, dict):
            raise OpenAIResponseError(
                "OpenAI returned an invalid response object",
                stage=ModelResponseFailureStage.HTTP_RESPONSE,
            )
        return value

    def _instructions(self, request: ModelRequest) -> str:
        identity = json.dumps(
            {"provider": self.continuation_provider, "model": self.model},
            ensure_ascii=False,
        )
        extra_system = "\n".join(
            message.content for message in request.messages if message.role is MessageRole.SYSTEM
        )
        sections = [request.agent.system_prompt]
        if extra_system:
            sections.append(extra_system)
        sections.append(
            "You may call multiple independent tools in one turn. Never invent a tool name. "
            "Every tool call must include every field listed in the function JSON Schema "
            "required array. The runtime-selected model identity is trusted metadata: "
            f"{identity}. When asked which provider or model is active, report exactly this "
            "metadata instead of relying on pretrained self-identity."
        )
        return "\n\n".join(sections)

    def _input(
        self,
        request: ModelRequest,
        name_to_tool: dict[str, ToolSpec],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        continuations = {
            continuation.step_index: continuation for continuation in request.provider_continuations
        }
        assistant_step = 0
        for message in request.messages:
            if message.role is MessageRole.SYSTEM:
                continue
            if message.role is MessageRole.ASSISTANT:
                assistant_step += 1
                continuation = continuations.get(assistant_step)
                if continuation is not None:
                    if continuation.provider != "openai" or continuation.model != self.model:
                        raise ProviderContinuationUnavailableError(
                            "provider continuation does not match the active OpenAI model"
                        )
                    output = continuation.payload.get("output")
                    if not isinstance(output, list) or not all(
                        isinstance(item, dict) for item in output
                    ):
                        raise ProviderContinuationUnavailableError(
                            "OpenAI provider continuation is malformed"
                        )
                    items.extend(deepcopy(output))
                    continue
                structured = _structured_turn(message.content)
                if request.tool_free and isinstance(
                    structured,
                    ToolCallTurn | ToolCallBatchTurn,
                ):
                    calls = (
                        structured.calls
                        if isinstance(structured, ToolCallBatchTurn)
                        else (structured,)
                    )
                    for index, call in enumerate(calls):
                        generated_id = hashlib.sha256(
                            f"{message.content}:{index}".encode()
                        ).hexdigest()[:12]
                        items.append(
                            {
                                "type": "function_call",
                                "call_id": call.call_id or f"wf-{generated_id}",
                                "name": _function_name(call.tool_id),
                                "arguments": json.dumps(
                                    call.arguments,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ),
                            }
                        )
                    continue
                if structured is not None:
                    raise ProviderContinuationUnavailableError(
                        "required OpenAI provider continuation history is unavailable"
                    )
                items.append({"role": "assistant", "content": message.content})
                continue
            if message.role is MessageRole.TOOL:
                if message.tool_call_id is None:
                    raise OpenAIResponseError(
                        "tool history is missing its provider call id",
                        stage=ModelResponseFailureStage.MESSAGE,
                    )
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": message.content,
                    }
                )
                continue
            items.append({"role": "user", "content": message.content})
        return items

    def _turn(
        self,
        response: dict[str, Any],
        name_to_tool: dict[str, ToolSpec],
    ) -> ModelTurn | ModelCompletion:
        output = response.get("output")
        if not isinstance(output, list) or not output:
            raise OpenAIResponseError(
                "OpenAI returned no response output",
                stage=ModelResponseFailureStage.CHOICE,
            )
        usage = _usage(response.get("usage"))
        calls = [
            item
            for item in output
            if isinstance(item, dict) and item.get("type") == "function_call"
        ]
        if calls:
            if not 1 <= len(calls) <= 8:
                raise OpenAIResponseError(
                    "OpenAI returned an invalid tool call count",
                    stage=ModelResponseFailureStage.MESSAGE,
                )
            parsed_calls: list[ToolCallTurn] = []
            delegation: DelegationTurn | None = None
            for call in calls:
                name = call.get("name")
                arguments = _arguments(call.get("arguments"))
                if name == DELEGATE_FUNCTION:
                    if len(calls) != 1:
                        raise OpenAIResponseError(
                            "delegation cannot be mixed with tool calls",
                            stage=ModelResponseFailureStage.MESSAGE,
                        )
                    try:
                        delegation = DelegationTurn(
                            agent_id=arguments["agent_id"],
                            task=arguments["task"],
                            usage=usage,
                        )
                    except (KeyError, TypeError, ValueError) as error:
                        raise OpenAIResponseError(
                            "OpenAI returned invalid delegation",
                            stage=ModelResponseFailureStage.MESSAGE,
                        ) from error
                    continue
                tool = name_to_tool.get(str(name))
                if tool is None:
                    raise OpenAIResponseError(
                        "OpenAI returned an unknown function",
                        stage=ModelResponseFailureStage.MESSAGE,
                    )
                parsed_calls.append(
                    ToolCallTurn(
                        call_id=str(call.get("call_id")) if call.get("call_id") else None,
                        tool_id=tool.tool_id,
                        arguments=arguments,
                    )
                )
            turn: ModelTurn
            if delegation is not None:
                turn = delegation
            elif len(parsed_calls) == 1:
                turn = parsed_calls[0].model_copy(update={"usage": usage})
            else:
                turn = ToolCallBatchTurn(calls=tuple(parsed_calls), usage=usage)
            return ModelCompletion(
                turn=turn,
                continuation=ProviderAssistantMessage(
                    provider="openai",
                    model=self.model,
                    payload={"role": "assistant", "output": deepcopy(output)},
                ),
            )
        text = _output_text(output)
        if not text:
            raise OpenAIResponseError(
                "OpenAI returned neither text nor a tool call",
                stage=ModelResponseFailureStage.EMPTY_TEXT,
            )
        return FinalTurn(content=text, usage=usage)

    def __repr__(self) -> str:
        return (
            f"OpenAIResponsesAdapter(model={self.model!r}, base_url={self.base_url!r}, "
            "credential=<redacted>)"
        )


def _function_name(tool_id: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9_-]", "_", tool_id)[:46]
    digest = hashlib.sha256(tool_id.encode()).hexdigest()[:10]
    return f"wf_{readable}_{digest}"[:64]


def _tool_payload(name: str, tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": tool.description,
        "parameters": tool.input_schema or {"type": "object"},
        "strict": False,
    }


def _delegation_payload() -> dict[str, Any]:
    return {
        "type": "function",
        "name": DELEGATE_FUNCTION,
        "description": "Delegate one bounded task to an available leaf Worker",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "task": {"type": "string", "maxLength": 4000},
            },
            "required": ["agent_id", "task"],
            "additionalProperties": False,
        },
        "strict": False,
    }


def _structured_turn(content: str) -> ModelTurn | None:
    try:
        value = json.loads(content)
    except ValueError:
        return None
    if not isinstance(value, dict) or value.get("kind") not in {
        "tool_call",
        "tool_call_batch",
        "delegation",
    }:
        return None
    try:
        if value["kind"] == "tool_call":
            return ToolCallTurn.model_validate(value)
        if value["kind"] == "tool_call_batch":
            return ToolCallBatchTurn.model_validate(value)
        return DelegationTurn.model_validate(value)
    except ValueError:
        return None


def _arguments(value: Any) -> dict[str, Any]:
    try:
        arguments = json.loads(value) if isinstance(value, str) else value
    except ValueError as error:
        raise OpenAIResponseError(
            "OpenAI returned malformed function arguments",
            stage=ModelResponseFailureStage.MESSAGE,
        ) from error
    if not isinstance(arguments, dict):
        raise OpenAIResponseError(
            "OpenAI function arguments must be an object",
            stage=ModelResponseFailureStage.MESSAGE,
        )
    return arguments


def _output_text(output: list[Any]) -> str:
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "output_text"
                and isinstance(block.get("text"), str)
            ):
                parts.append(block["text"])
    return "\n".join(parts).strip()


def _usage(value: Any) -> ModelUsage:
    if not isinstance(value, dict):
        return ModelUsage()
    input_tokens = value.get("input_tokens")
    output_tokens = value.get("output_tokens")
    if not _token_count(input_tokens) or not _token_count(output_tokens):
        return ModelUsage()
    return ModelUsage(input_tokens=input_tokens, output_tokens=output_tokens)


def _token_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0

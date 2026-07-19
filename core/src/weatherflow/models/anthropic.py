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
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicError(ConnectionError):
    pass


class AnthropicRetryableError(AnthropicError):
    pass


class AnthropicAuthenticationError(AnthropicError):
    pass


class AnthropicResponseError(AnthropicError):
    def __init__(
        self,
        message: str,
        *,
        stage: ModelResponseFailureStage = ModelResponseFailureStage.UNKNOWN,
    ) -> None:
        super().__init__(message)
        self.stage = stage


class AnthropicMessagesAdapter:
    """Anthropic Messages adapter with opaque signed-thinking replay."""

    continuation_provider = "anthropic"

    def __init__(
        self,
        *,
        broker: CredentialBroker,
        credential_ref: CredentialRef,
        model: str,
        base_url: str = "https://api.anthropic.com/v1",
        max_tokens: int = 2048,
        timeout_seconds: float = 120,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if credential_ref.provider != "anthropic" or credential_ref.name != "api_key":
            raise ValueError("Anthropic adapter requires the fixed anthropic credential reference")
        if not model.startswith("claude-") or len(model) > 200:
            raise ValueError("invalid Anthropic model identifier")
        normalized_url = base_url.rstrip("/")
        if not normalized_url.startswith("https://"):
            raise ValueError("model base URL must use HTTPS")
        if not 1 <= max_tokens <= 128_000:
            raise ValueError("max_tokens must be between 1 and 128000")
        self.broker = broker
        self.credential_ref = credential_ref
        self.model = model
        self.base_url = normalized_url
        self.max_tokens = max_tokens
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
            "max_tokens": self.max_tokens,
            "system": self._system(request),
            "messages": self._messages(request),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = {"type": "auto"}

        async def transport(secret: str) -> dict[str, Any]:
            return await self._post("messages", secret, payload=payload)

        try:
            response = await self.broker.call(self.credential_ref, transport)
        except CredentialUnavailableError as error:
            raise AnthropicAuthenticationError("Anthropic credential is unavailable") from error
        return self._turn(response, name_to_tool)

    async def list_models(
        self,
        *,
        query: dict[str, str] | None = None,
    ) -> tuple[str, ...]:
        params = {"limit": "1000", **(query or {})}

        async def transport(secret: str) -> tuple[str, ...]:
            response = await self._get("models", secret, query=params)
            data = response.get("data")
            if not isinstance(data, list):
                raise AnthropicResponseError(
                    "Anthropic model catalog returned an invalid response",
                    stage=ModelResponseFailureStage.HTTP_RESPONSE,
                )
            models = tuple(
                item["id"]
                for item in data
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
            )
            if not models:
                raise AnthropicResponseError(
                    "Anthropic model catalog is empty",
                    stage=ModelResponseFailureStage.PROVIDER_STATUS,
                )
            return tuple(dict.fromkeys(models))

        try:
            return await self.broker.call(self.credential_ref, transport)
        except CredentialUnavailableError as error:
            raise AnthropicAuthenticationError("Anthropic credential is unavailable") from error

    async def verify(self) -> None:
        if self.model not in await self.list_models():
            raise AnthropicResponseError(
                "configured Anthropic model is not available",
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
                headers=self._headers(secret),
                json=payload,
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise AnthropicRetryableError("Anthropic request is unavailable") from error
        return self._response(response)

    async def _get(
        self,
        path: str,
        secret: str,
        *,
        query: dict[str, str],
    ) -> dict[str, Any]:
        try:
            response = await self.client.get(
                f"{self.base_url}/{path}",
                headers=self._headers(secret),
                params=query,
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise AnthropicRetryableError("Anthropic request is unavailable") from error
        return self._response(response)

    @staticmethod
    def _headers(secret: str) -> dict[str, str]:
        return {
            "x-api-key": secret,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    @staticmethod
    def _response(response: httpx.Response) -> dict[str, Any]:
        if response.status_code in {401, 403}:
            raise AnthropicAuthenticationError("Anthropic credential was rejected")
        if response.status_code in {408, 409, 429, 529} or response.status_code >= 500:
            raise AnthropicRetryableError(
                f"Anthropic request failed with retryable status {response.status_code}"
            )
        if response.is_error:
            raise AnthropicResponseError(
                f"Anthropic request failed with status {response.status_code}",
                stage=ModelResponseFailureStage.HTTP_RESPONSE,
            )
        try:
            value = response.json()
        except ValueError as error:
            raise AnthropicResponseError(
                "Anthropic returned invalid JSON",
                stage=ModelResponseFailureStage.HTTP_RESPONSE,
            ) from error
        if not isinstance(value, dict):
            raise AnthropicResponseError(
                "Anthropic returned an invalid response object",
                stage=ModelResponseFailureStage.HTTP_RESPONSE,
            )
        return value

    def _system(self, request: ModelRequest) -> str:
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
            "Every tool call must include every field listed in the input schema required array. "
            f"The runtime-selected model identity is trusted metadata: {identity}. When asked "
            "which provider or model is active, report exactly this metadata instead of relying "
            "on pretrained self-identity."
        )
        return "\n\n".join(sections)

    def _messages(self, request: ModelRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
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
                    if continuation.provider != "anthropic" or continuation.model != self.model:
                        raise ProviderContinuationUnavailableError(
                            "provider continuation does not match the active Anthropic model"
                        )
                    role = continuation.payload.get("role")
                    content = continuation.payload.get("content")
                    if role != "assistant" or not isinstance(content, list):
                        raise ProviderContinuationUnavailableError(
                            "Anthropic provider continuation is malformed"
                        )
                    messages.append(deepcopy(continuation.payload))
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
                    content = []
                    for index, call in enumerate(calls):
                        generated_id = hashlib.sha256(
                            f"{message.content}:{index}".encode()
                        ).hexdigest()[:12]
                        content.append(
                            {
                                "type": "tool_use",
                                "id": call.call_id or f"wf-{generated_id}",
                                "name": _function_name(call.tool_id),
                                "input": call.arguments,
                            }
                        )
                    messages.append({"role": "assistant", "content": content})
                    continue
                if structured is not None:
                    raise ProviderContinuationUnavailableError(
                        "required Anthropic provider continuation history is unavailable"
                    )
                messages.append({"role": "assistant", "content": message.content})
                continue
            if message.role is MessageRole.TOOL:
                if message.tool_call_id is None:
                    raise AnthropicResponseError(
                        "tool history is missing its provider call id",
                        stage=ModelResponseFailureStage.MESSAGE,
                    )
                result = {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content,
                }
                prior_content = messages[-1].get("content") if messages else None
                if (
                    messages
                    and messages[-1].get("role") == "user"
                    and isinstance(prior_content, list)
                    and all(
                        isinstance(item, dict) and item.get("type") == "tool_result"
                        for item in prior_content
                    )
                ):
                    prior_content.append(result)
                else:
                    messages.append({"role": "user", "content": [result]})
                continue
            messages.append({"role": "user", "content": message.content})
        return messages

    def _turn(
        self,
        response: dict[str, Any],
        name_to_tool: dict[str, ToolSpec],
    ) -> ModelTurn | ModelCompletion:
        content = response.get("content")
        if not isinstance(content, list) or not content:
            raise AnthropicResponseError(
                "Anthropic returned no response content",
                stage=ModelResponseFailureStage.CHOICE,
            )
        usage = _usage(response.get("usage"))
        calls = [
            item for item in content if isinstance(item, dict) and item.get("type") == "tool_use"
        ]
        if calls:
            if response.get("stop_reason") != "tool_use" or not 1 <= len(calls) <= 8:
                raise AnthropicResponseError(
                    "Anthropic returned an invalid tool-use response",
                    stage=ModelResponseFailureStage.MESSAGE,
                )
            parsed_calls: list[ToolCallTurn] = []
            delegation: DelegationTurn | None = None
            for call in calls:
                name = call.get("name")
                arguments = call.get("input")
                if not isinstance(arguments, dict):
                    raise AnthropicResponseError(
                        "Anthropic tool input must be an object",
                        stage=ModelResponseFailureStage.MESSAGE,
                    )
                if name == DELEGATE_FUNCTION:
                    if len(calls) != 1:
                        raise AnthropicResponseError(
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
                        raise AnthropicResponseError(
                            "Anthropic returned invalid delegation",
                            stage=ModelResponseFailureStage.MESSAGE,
                        ) from error
                    continue
                tool = name_to_tool.get(str(name))
                if tool is None:
                    raise AnthropicResponseError(
                        "Anthropic returned an unknown function",
                        stage=ModelResponseFailureStage.MESSAGE,
                    )
                parsed_calls.append(
                    ToolCallTurn(
                        call_id=str(call.get("id")) if call.get("id") else None,
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
                    provider="anthropic",
                    model=self.model,
                    payload={"role": "assistant", "content": deepcopy(content)},
                ),
            )
        text = "\n".join(
            item["text"]
            for item in content
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ).strip()
        if not text:
            raise AnthropicResponseError(
                "Anthropic returned neither text nor a tool call",
                stage=ModelResponseFailureStage.EMPTY_TEXT,
            )
        return FinalTurn(content=text, usage=usage)

    def __repr__(self) -> str:
        return (
            f"AnthropicMessagesAdapter(model={self.model!r}, base_url={self.base_url!r}, "
            "credential=<redacted>)"
        )


def _function_name(tool_id: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9_-]", "_", tool_id)[:75]
    digest = hashlib.sha256(tool_id.encode()).hexdigest()[:10]
    return f"wf_{readable}_{digest}"[:128]


def _tool_payload(name: str, tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": name,
        "description": tool.description,
        "input_schema": tool.input_schema or {"type": "object"},
        "strict": False,
    }


def _delegation_payload() -> dict[str, Any]:
    return {
        "name": DELEGATE_FUNCTION,
        "description": "Delegate one bounded task to an available leaf Worker",
        "input_schema": {
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


def _usage(value: Any) -> ModelUsage:
    if not isinstance(value, dict):
        return ModelUsage()
    counts = [
        value.get("input_tokens"),
        value.get("cache_creation_input_tokens", 0) or 0,
        value.get("cache_read_input_tokens", 0) or 0,
        value.get("output_tokens"),
    ]
    if not all(_token_count(count) for count in counts):
        return ModelUsage()
    return ModelUsage(
        input_tokens=counts[0] + counts[1] + counts[2],
        output_tokens=counts[3],
    )


def _token_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0

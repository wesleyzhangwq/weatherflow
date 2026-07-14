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
from weatherflow.models.pricing import (
    PRICING_CATALOG_VERSION,
    ModelTokenPrice,
    resolve_token_price,
)
from weatherflow.runtime import (
    AgentMessage,
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
THINK_PATTERN = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


class MiniMaxError(ConnectionError):
    pass


class MiniMaxRetryableError(MiniMaxError):
    pass


class MiniMaxAuthenticationError(MiniMaxError):
    pass


class MiniMaxResponseError(MiniMaxError):
    pass


class OpenAICompatibleAdapter:
    def __init__(
        self,
        *,
        provider: str,
        broker: CredentialBroker,
        credential_ref: CredentialRef,
        model: str = "MiniMax-M3",
        base_url: str = "https://api.minimax.io/v1",
        max_completion_tokens: int = 2048,
        timeout_seconds: float = 120,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", provider):
            raise ValueError("invalid provider identifier")
        if not model.strip() or len(model) > 200:
            raise ValueError("invalid model identifier")
        normalized_url = base_url.rstrip("/")
        if not normalized_url.startswith("https://"):
            raise ValueError("model base URL must use HTTPS")
        if not 1 <= max_completion_tokens <= 2048:
            raise ValueError("max_completion_tokens must be between 1 and 2048")
        self.broker = broker
        self.provider = provider
        self.credential_ref = credential_ref
        self.model = model
        self.base_url = normalized_url
        self.max_completion_tokens = max_completion_tokens
        self.timeout_seconds = timeout_seconds
        self.client = client or httpx.AsyncClient()
        self.token_price = resolve_token_price(
            provider=provider,
            model=model,
            base_url=normalized_url,
        )
        self.pricing_catalog_version = (
            PRICING_CATALOG_VERSION if self.token_price is not None else None
        )
        self.continuation_provider = (
            provider if provider == "minimax" and model.startswith("MiniMax-M2") else None
        )
        self.continuation_model = model if self.continuation_provider is not None else None

    async def complete(self, request: ModelRequest) -> ModelTurn | ModelCompletion:
        name_to_tool = {_function_name(tool.tool_id): tool for tool in request.tools}
        tools = [_tool_payload(name, tool) for name, tool in name_to_tool.items()]
        if not request.agent.is_leaf:
            tools.append(_delegation_payload())
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(request, name_to_tool),
            "stream": False,
            "max_tokens": self.max_completion_tokens,
        }
        if self.provider == "minimax":
            payload.update(
                {
                    "max_completion_tokens": payload.pop("max_tokens"),
                    "temperature": 1.0,
                    "top_p": 0.95,
                    "reasoning_split": True,
                }
            )
            if self.model.startswith("MiniMax-M3"):
                payload["thinking"] = {"type": "disabled"}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async def transport(secret: str) -> dict[str, Any]:
            return await self._post(payload, secret)

        try:
            response = await self.broker.call(self.credential_ref, transport)
        except CredentialUnavailableError as error:
            raise MiniMaxAuthenticationError("model credential is unavailable") from error
        return self._turn(response, name_to_tool)

    async def list_models(
        self,
        *,
        query: dict[str, str] | None = None,
    ) -> tuple[str, ...]:
        async def transport(secret: str) -> tuple[str, ...]:
            try:
                response = await self.client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {secret}"},
                    params=query,
                    timeout=self.timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                raise MiniMaxRetryableError("model verification unavailable") from error
            self._raise_for_status(response)
            try:
                payload = response.json()
            except ValueError as error:
                raise MiniMaxResponseError("model catalog returned invalid JSON") from error
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise MiniMaxResponseError("model catalog returned an invalid response")
            models = tuple(
                item["id"]
                for item in payload["data"]
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
            )
            if not models:
                raise MiniMaxResponseError("model catalog is empty")
            return tuple(dict.fromkeys(models))

        try:
            return await self.broker.call(self.credential_ref, transport)
        except CredentialUnavailableError as error:
            raise MiniMaxAuthenticationError("model credential is unavailable") from error

    async def verify(self) -> None:
        models = await self.list_models()
        if self.model not in models:
            raise MiniMaxResponseError("configured model is not available")

    async def _post(self, payload: dict[str, Any], secret: str) -> dict[str, Any]:
        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {secret}"},
                json=payload,
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise MiniMaxRetryableError("model request unavailable") from error
        self._raise_for_status(response)
        try:
            value = response.json()
        except ValueError as error:
            raise MiniMaxResponseError("model provider returned invalid JSON") from error
        if not isinstance(value, dict):
            raise MiniMaxResponseError("model provider returned an invalid response object")
        base_response = value.get("base_resp")
        if isinstance(base_response, dict) and base_response.get("status_code") not in {
            None,
            0,
        }:
            raise MiniMaxResponseError("model provider returned a provider-level error")
        return value

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise MiniMaxAuthenticationError(f"{self.provider} credential was rejected")
        if response.status_code in {408, 409, 429} or response.status_code >= 500:
            raise MiniMaxRetryableError(
                f"{self.provider} request failed with retryable status {response.status_code}"
            )
        if response.is_error:
            raise MiniMaxResponseError(
                f"{self.provider} request failed with status {response.status_code}"
            )

    def _messages(
        self,
        request: ModelRequest,
        name_to_tool: dict[str, ToolSpec],
    ) -> list[dict[str, Any]]:
        identity = json.dumps(
            {"provider": self.provider, "model": self.model},
            ensure_ascii=False,
        )
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    f"{request.agent.system_prompt}\n\n"
                    "You may call multiple independent tools in one turn. "
                    "Never invent a tool name. "
                    "Every tool call must include every field listed in the function's "
                    "JSON Schema required array.\n\n"
                    "The runtime-selected model identity is trusted metadata: "
                    f"{identity}. "
                    "When asked which provider or model is active, report exactly this "
                    "metadata instead of relying on pretrained self-identity."
                ),
            }
        ]
        tool_to_name = {tool.tool_id: name for name, tool in name_to_tool.items()}
        continuation_by_step = {
            continuation.step_index: continuation for continuation in request.provider_continuations
        }
        assistant_step = 0
        for message in request.messages:
            if message.role is MessageRole.ASSISTANT:
                assistant_step += 1
                continuation = continuation_by_step.get(assistant_step)
                if continuation is not None:
                    if (
                        continuation.provider != self.continuation_provider
                        or continuation.model != self.continuation_model
                    ):
                        raise ProviderContinuationUnavailableError(
                            "provider continuation does not match the active model"
                        )
                    messages.append(deepcopy(continuation.payload))
                    continue
                if self.continuation_provider is not None and _assistant_requires_continuation(
                    message.content
                ):
                    raise ProviderContinuationUnavailableError(
                        "required provider continuation history is unavailable"
                    )
            messages.append(self._message(message, tool_to_name))
        return messages

    @staticmethod
    def _message(message: AgentMessage, tool_to_name: dict[str, str]) -> dict[str, Any]:
        if message.role is MessageRole.ASSISTANT:
            parsed = _assistant_turn(message.content)
            if isinstance(parsed, ToolCallTurn):
                function_name = tool_to_name.get(parsed.tool_id)
                if function_name is None:
                    raise MiniMaxResponseError("tool history is outside the frozen snapshot")
                generated_id = f"wf-{hashlib.sha256(message.content.encode()).hexdigest()[:12]}"
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": parsed.call_id or generated_id,
                            "type": "function",
                            "function": {
                                "name": function_name,
                                "arguments": json.dumps(
                                    parsed.arguments,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ),
                            },
                        }
                    ],
                }
            if isinstance(parsed, ToolCallBatchTurn):
                tool_calls = []
                for index, call in enumerate(parsed.calls):
                    function_name = tool_to_name.get(call.tool_id)
                    if function_name is None:
                        raise MiniMaxResponseError("tool history is outside the frozen snapshot")
                    fingerprint = hashlib.sha256(f"{message.content}:{index}".encode()).hexdigest()[
                        :12
                    ]
                    generated_id = f"wf-{fingerprint}"
                    tool_calls.append(
                        {
                            "id": call.call_id or generated_id,
                            "type": "function",
                            "function": {
                                "name": function_name,
                                "arguments": json.dumps(
                                    call.arguments,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ),
                            },
                        }
                    )
                return {"role": "assistant", "content": None, "tool_calls": tool_calls}
        if message.role is MessageRole.TOOL:
            function_name = tool_to_name.get(message.name or "")
            if function_name is None or message.tool_call_id is None:
                return {
                    "role": "user",
                    "content": f"Tool observation ({message.name or 'unknown'}): {message.content}",
                }
            return {
                "role": "tool",
                "name": function_name,
                "tool_call_id": message.tool_call_id,
                "content": message.content,
            }
        return {"role": message.role.value, "content": message.content}

    def _turn(
        self,
        response: dict[str, Any],
        name_to_tool: dict[str, ToolSpec],
    ) -> ModelTurn | ModelCompletion:
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise MiniMaxResponseError("model provider returned an invalid choice count")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise MiniMaxResponseError("model provider returned no assistant message")
        usage = _usage(response.get("usage"), self.token_price)
        provider_message = deepcopy(message)
        provider_message.setdefault("role", "assistant")

        def completed(turn: ModelTurn) -> ModelTurn | ModelCompletion:
            if self.continuation_provider is None:
                return turn
            continuation = (
                ProviderAssistantMessage(
                    provider=self.continuation_provider,
                    model=self.continuation_model or self.model,
                    payload=provider_message,
                )
                if isinstance(turn, ToolCallTurn | ToolCallBatchTurn | DelegationTurn)
                else None
            )
            return ModelCompletion(turn=turn, continuation=continuation)

        calls = message.get("tool_calls")
        if calls:
            if not isinstance(calls, list) or not 1 <= len(calls) <= 8:
                raise MiniMaxResponseError("model provider returned an invalid tool call count")
            parsed_calls: list[ToolCallTurn] = []
            delegation: DelegationTurn | None = None
            for call in calls:
                function = call.get("function") if isinstance(call, dict) else None
                if not isinstance(function, dict):
                    raise MiniMaxResponseError("model provider returned an invalid tool call")
                name = function.get("name")
                arguments = _arguments(function.get("arguments"))
                if name == DELEGATE_FUNCTION:
                    if len(calls) != 1:
                        raise MiniMaxResponseError(
                            "delegation cannot be mixed with a tool-call batch"
                        )
                    try:
                        delegation = DelegationTurn(
                            agent_id=arguments["agent_id"],
                            task=arguments["task"],
                            usage=usage,
                        )
                    except (KeyError, TypeError, ValueError) as error:
                        raise MiniMaxResponseError(
                            "model provider returned invalid delegation"
                        ) from error
                    continue
                tool = name_to_tool.get(str(name))
                if tool is None:
                    raise MiniMaxResponseError("model provider returned an unknown function")
                parsed_calls.append(
                    ToolCallTurn(
                        call_id=str(call.get("id")) if call.get("id") else None,
                        tool_id=tool.tool_id,
                        arguments=arguments,
                    )
                )
            if delegation is not None:
                return completed(delegation)
            if len(parsed_calls) == 1:
                return completed(parsed_calls[0].model_copy(update={"usage": usage}))
            return completed(ToolCallBatchTurn(calls=tuple(parsed_calls), usage=usage))
        content = message.get("content")
        if not isinstance(content, str):
            raise MiniMaxResponseError("model provider returned neither text nor a tool call")
        cleaned = THINK_PATTERN.sub("", content).strip()
        if not cleaned:
            raise MiniMaxResponseError("model provider returned empty final text")
        return completed(FinalTurn(content=cleaned, usage=usage))

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleAdapter(provider={self.provider!r}, model={self.model!r}, "
            f"base_url={self.base_url!r}, credential=<redacted>)"
        )


class MiniMaxAdapter(OpenAICompatibleAdapter):
    def __init__(
        self,
        *,
        broker: CredentialBroker,
        credential_ref: CredentialRef,
        model: str = "MiniMax-M3",
        base_url: str = "https://api.minimax.io/v1",
        max_completion_tokens: int = 2048,
        timeout_seconds: float = 120,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not model.startswith("MiniMax-"):
            raise ValueError("unsupported MiniMax model identifier")
        super().__init__(
            provider="minimax",
            broker=broker,
            credential_ref=credential_ref,
            model=model,
            base_url=base_url,
            max_completion_tokens=max_completion_tokens,
            timeout_seconds=timeout_seconds,
            client=client,
        )


def _function_name(tool_id: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9_-]", "_", tool_id)[:46]
    digest = hashlib.sha256(tool_id.encode()).hexdigest()[:10]
    return f"wf_{readable}_{digest}"[:64]


def _tool_payload(name: str, tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": tool.description,
            "parameters": tool.input_schema or {"type": "object"},
        },
    }


def _delegation_payload() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
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
        },
    }


def _assistant_turn(content: str) -> ModelTurn | None:
    try:
        value = json.loads(content)
    except ValueError:
        return None
    if not isinstance(value, dict) or value.get("kind") not in {
        "tool_call",
        "tool_call_batch",
    }:
        return None
    try:
        return (
            ToolCallTurn.model_validate(value)
            if value.get("kind") == "tool_call"
            else ToolCallBatchTurn.model_validate(value)
        )
    except ValueError:
        return None


def _assistant_requires_continuation(content: str) -> bool:
    try:
        value = json.loads(content)
    except ValueError:
        return False
    return isinstance(value, dict) and value.get("kind") in {
        "tool_call",
        "tool_call_batch",
        "delegation",
    }


def _arguments(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError as error:
        raise MiniMaxResponseError("MiniMax returned malformed function arguments") from error
    if not isinstance(parsed, dict):
        raise MiniMaxResponseError("MiniMax function arguments must be an object")
    return parsed


def _usage(value: Any, token_price: ModelTokenPrice | None) -> ModelUsage:
    if not isinstance(value, dict):
        return ModelUsage()
    if "prompt_tokens" not in value or "completion_tokens" not in value:
        return ModelUsage()
    input_tokens = value["prompt_tokens"]
    output_tokens = value["completion_tokens"]
    if (
        not isinstance(input_tokens, int)
        or isinstance(input_tokens, bool)
        or not isinstance(output_tokens, int)
        or isinstance(output_tokens, bool)
    ):
        return ModelUsage()
    if input_tokens < 0 or output_tokens < 0:
        return ModelUsage()
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=(
            token_price.estimate_usd(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            if token_price is not None
            else None
        ),
    )

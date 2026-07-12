import hashlib
import json
import re
from typing import Any

import httpx

from weatherflow.capabilities import ToolSpec
from weatherflow.extensions import (
    CredentialBroker,
    CredentialRef,
    CredentialUnavailableError,
)
from weatherflow.runtime import (
    AgentMessage,
    DelegationTurn,
    FinalTurn,
    MessageRole,
    ModelRequest,
    ModelTurn,
    ModelUsage,
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


class MiniMaxAdapter:
    def __init__(
        self,
        *,
        broker: CredentialBroker,
        credential_ref: CredentialRef,
        model: str = "MiniMax-M2.7",
        base_url: str = "https://api.minimax.io/v1",
        max_completion_tokens: int = 2048,
        timeout_seconds: float = 120,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not model.startswith("MiniMax-"):
            raise ValueError("unsupported MiniMax model identifier")
        normalized_url = base_url.rstrip("/")
        if not normalized_url.startswith("https://"):
            raise ValueError("MiniMax base URL must use HTTPS")
        if not 1 <= max_completion_tokens <= 2048:
            raise ValueError("max_completion_tokens must be between 1 and 2048")
        self.broker = broker
        self.credential_ref = credential_ref
        self.model = model
        self.base_url = normalized_url
        self.max_completion_tokens = max_completion_tokens
        self.timeout_seconds = timeout_seconds
        self.client = client or httpx.AsyncClient()

    async def complete(self, request: ModelRequest) -> ModelTurn:
        name_to_tool = {_function_name(tool.tool_id): tool for tool in request.tools}
        tools = [_tool_payload(name, tool) for name, tool in name_to_tool.items()]
        if not request.agent.is_leaf:
            tools.append(_delegation_payload())
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(request, name_to_tool),
            "stream": False,
            "max_completion_tokens": self.max_completion_tokens,
            "temperature": 1.0,
            "top_p": 0.95,
            "reasoning_split": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async def transport(secret: str) -> dict[str, Any]:
            return await self._post(payload, secret)

        try:
            response = await self.broker.call(self.credential_ref, transport)
        except CredentialUnavailableError as error:
            raise MiniMaxAuthenticationError("MiniMax credential is unavailable") from error
        return self._turn(response, name_to_tool)

    async def verify(self) -> None:
        async def transport(secret: str) -> None:
            try:
                response = await self.client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {secret}"},
                    timeout=self.timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                raise MiniMaxRetryableError("MiniMax model verification unavailable") from error
            self._raise_for_status(response)
            data = response.json().get("data", [])
            if not any(item.get("id") == self.model for item in data if isinstance(item, dict)):
                raise MiniMaxResponseError("configured MiniMax model is not available")

        try:
            await self.broker.call(self.credential_ref, transport)
        except CredentialUnavailableError as error:
            raise MiniMaxAuthenticationError("MiniMax credential is unavailable") from error

    async def _post(self, payload: dict[str, Any], secret: str) -> dict[str, Any]:
        try:
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {secret}"},
                json=payload,
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise MiniMaxRetryableError("MiniMax request unavailable") from error
        self._raise_for_status(response)
        try:
            value = response.json()
        except ValueError as error:
            raise MiniMaxResponseError("MiniMax returned invalid JSON") from error
        if not isinstance(value, dict):
            raise MiniMaxResponseError("MiniMax returned an invalid response object")
        base_response = value.get("base_resp")
        if isinstance(base_response, dict) and base_response.get("status_code") not in {
            None,
            0,
        }:
            raise MiniMaxResponseError("MiniMax returned a provider-level error")
        return value

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise MiniMaxAuthenticationError("MiniMax credential was rejected")
        if response.status_code in {408, 409, 429} or response.status_code >= 500:
            raise MiniMaxRetryableError(
                f"MiniMax request failed with retryable status {response.status_code}"
            )
        if response.is_error:
            raise MiniMaxResponseError(f"MiniMax request failed with status {response.status_code}")

    def _messages(
        self,
        request: ModelRequest,
        name_to_tool: dict[str, ToolSpec],
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    f"{request.agent.system_prompt}\n\n"
                    "Call at most one tool per turn. Never invent a tool name."
                ),
            }
        ]
        tool_to_name = {tool.tool_id: name for name, tool in name_to_tool.items()}
        for message in request.messages:
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

    @staticmethod
    def _turn(response: dict[str, Any], name_to_tool: dict[str, ToolSpec]) -> ModelTurn:
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise MiniMaxResponseError("MiniMax returned an invalid choice count")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise MiniMaxResponseError("MiniMax returned no assistant message")
        usage = _usage(response.get("usage"))
        calls = message.get("tool_calls")
        if calls:
            if not isinstance(calls, list) or len(calls) != 1:
                raise MiniMaxResponseError("MiniMax returned multiple tool calls")
            call = calls[0]
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict):
                raise MiniMaxResponseError("MiniMax returned an invalid tool call")
            name = function.get("name")
            arguments = _arguments(function.get("arguments"))
            if name == DELEGATE_FUNCTION:
                try:
                    return DelegationTurn(
                        agent_id=arguments["agent_id"],
                        task=arguments["task"],
                        usage=usage,
                    )
                except (KeyError, TypeError, ValueError) as error:
                    raise MiniMaxResponseError("MiniMax returned invalid delegation") from error
            tool = name_to_tool.get(str(name))
            if tool is None:
                raise MiniMaxResponseError("MiniMax returned an unknown function")
            return ToolCallTurn(
                call_id=str(call.get("id")) if call.get("id") else None,
                tool_id=tool.tool_id,
                arguments=arguments,
                usage=usage,
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise MiniMaxResponseError("MiniMax returned neither text nor a tool call")
        cleaned = THINK_PATTERN.sub("", content).strip()
        if not cleaned:
            raise MiniMaxResponseError("MiniMax returned empty final text")
        return FinalTurn(content=cleaned, usage=usage)

    def __repr__(self) -> str:
        return (
            f"MiniMaxAdapter(model={self.model!r}, base_url={self.base_url!r}, "
            "credential=<redacted>)"
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
    if not isinstance(value, dict) or value.get("kind") != "tool_call":
        return None
    try:
        return ToolCallTurn.model_validate(value)
    except ValueError:
        return None


def _arguments(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError as error:
        raise MiniMaxResponseError("MiniMax returned malformed function arguments") from error
    if not isinstance(parsed, dict):
        raise MiniMaxResponseError("MiniMax function arguments must be an object")
    return parsed


def _usage(value: Any) -> ModelUsage:
    if not isinstance(value, dict):
        return ModelUsage()
    return ModelUsage(
        input_tokens=max(0, int(value.get("prompt_tokens") or 0)),
        output_tokens=max(0, int(value.get("completion_tokens") or 0)),
    )

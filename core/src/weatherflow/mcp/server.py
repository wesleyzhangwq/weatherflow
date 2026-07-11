from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from weatherflow.bootstrap import RuntimeContainer


SERVER_TOOLS = (
    {
        "name": "weatherflow.submit_run",
        "description": "Create an idempotent WeatherFlow Run through the sole Run Coordinator",
        "inputSchema": {
            "type": "object",
            "required": ["intent", "client_request_id"],
        },
        "annotations": {"readOnlyHint": False, "idempotentHint": True},
    },
    {
        "name": "weatherflow.get_run",
        "description": "Read a WeatherFlow Run",
        "inputSchema": {"type": "object", "required": ["run_id"]},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "weatherflow.timeline",
        "description": "Read the user-visible timeline for a Run",
        "inputSchema": {"type": "object", "required": ["run_id"]},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "weatherflow.list_approvals",
        "description": "List current WeatherFlow Approval records",
        "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "weatherflow.decide_approval",
        "description": "Record an explicit user Approval decision and optionally resume the Run",
        "inputSchema": {
            "type": "object",
            "required": ["approval_id", "decision", "expected_version"],
        },
        "annotations": {"readOnlyHint": False, "idempotentHint": True},
    },
)


class WeatherFlowMCPServer:
    def __init__(self, container: RuntimeContainer) -> None:
        self.container = container

    async def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})
        if method == "initialize":
            return self._result(
                request_id,
                {
                    "protocolVersion": "2025-03-26",
                    "serverInfo": {"name": "weatherflow", "version": "3.0.0"},
                    "capabilities": {"tools": {"listChanged": False}},
                },
            )
        if method == "tools/list":
            return self._result(request_id, {"tools": list(SERVER_TOOLS)})
        if method != "tools/call":
            return self._error(request_id, -32601, "method not found")
        if not isinstance(params, dict):
            return self._error(request_id, -32602, "invalid params")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return self._error(request_id, -32602, "invalid arguments")
        try:
            output = await self._call_tool(str(name), arguments)
        except LookupError:
            return self._error(request_id, -32602, "unknown tool or record")
        except (TypeError, ValueError):
            return self._error(request_id, -32602, "invalid tool arguments")
        return self._result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            output,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )[:8_000],
                    }
                ],
                "structuredContent": output,
                "isError": False,
            },
        )

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "weatherflow.submit_run":
            intent = self._required_string(arguments, "intent")
            client_request_id = self._required_string(arguments, "client_request_id")
            workspace_id = arguments.get("workspace_id")
            if workspace_id is not None and not isinstance(workspace_id, str):
                raise TypeError("workspace_id")
            run, outcome = await self.container.submit_run(
                user_intent=intent,
                client_request_id=client_request_id,
                workspace_id=workspace_id,
                execute=bool(arguments.get("execute", True)),
            )
            stored = await self.container.runs.get(run.id)
            if stored is None:
                raise LookupError(run.id)
            return {
                "run": stored.model_dump(mode="json"),
                "outcome": outcome.model_dump(mode="json") if outcome else None,
            }
        if name == "weatherflow.get_run":
            run = await self.container.runs.get(self._required_string(arguments, "run_id"))
            if run is None:
                raise LookupError("run")
            return {"run": run.model_dump(mode="json")}
        if name == "weatherflow.timeline":
            run_id = self._required_string(arguments, "run_id")
            if await self.container.runs.get(run_id) is None:
                raise LookupError(run_id)
            events = await self.container.ledger.list_correlation(run_id, limit=1000)
            return {"events": [event.model_dump(mode="json") for event in events]}
        if name == "weatherflow.list_approvals":
            approvals = await self.container.approvals.list_all()
            return {"approvals": [approval.model_dump(mode="json") for approval in approvals]}
        if name == "weatherflow.decide_approval":
            decision = self._required_string(arguments, "decision")
            if decision not in {"approve", "deny"}:
                raise ValueError("decision")
            expected_version = arguments.get("expected_version")
            if not isinstance(expected_version, int):
                raise TypeError("expected_version")
            bundle = await self.container.approval_coordinator.decide(
                approval_id=self._required_string(arguments, "approval_id"),
                expected_version=expected_version,
                approved=decision == "approve",
                decided_by="mcp_user",
                rationale=(
                    str(arguments["rationale"])[:1_000]
                    if arguments.get("rationale") is not None
                    else None
                ),
            )
            if arguments.get("resume", True):
                await self.container.resume_run(bundle.run.id)
            run = await self.container.runs.get(bundle.run.id)
            approval = await self.container.approvals.get(bundle.approval.id)
            action = await self.container.actions.get(bundle.action.id)
            if approval is None or action is None:
                raise LookupError(bundle.approval.id)
            return {
                "approval": approval.model_dump(mode="json"),
                "action": action.model_dump(mode="json"),
                "run": run.model_dump(mode="json") if run else None,
            }
        raise LookupError(name)

    @staticmethod
    def _required_string(arguments: dict[str, Any], name: str) -> str:
        value = arguments.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > 4_000:
            raise TypeError(name)
        return value.strip()

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


async def serve_stdio(container: RuntimeContainer) -> None:
    server = WeatherFlowMCPServer(container)
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            return
        try:
            request = json.loads(line)
            response = await server.handle(request)
        except (json.JSONDecodeError, TypeError):
            response = WeatherFlowMCPServer._error(None, -32700, "parse error")
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()

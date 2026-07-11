from pathlib import Path

from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings
from weatherflow.mcp import WeatherFlowMCPServer


async def call(server, request_id: int, name: str, arguments: dict):
    return await server.handle(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )


async def test_server_exposes_single_run_path_and_idempotent_submission(
    tmp_path: Path,
) -> None:
    container = await RuntimeContainer.create(Settings(data_dir=tmp_path))
    server = WeatherFlowMCPServer(container)

    initialized = await server.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    listed = await server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    first = await call(
        server,
        3,
        "weatherflow.submit_run",
        {
            "intent": "Explain WeatherFlow",
            "client_request_id": "mcp-request-1",
            "execute": False,
        },
    )
    repeated = await call(
        server,
        4,
        "weatherflow.submit_run",
        {
            "intent": "Ignored retry",
            "client_request_id": "mcp-request-1",
            "execute": False,
        },
    )
    run_id = first["result"]["structuredContent"]["run"]["id"]
    status = await call(
        server,
        5,
        "weatherflow.get_run",
        {"run_id": run_id},
    )

    assert initialized["result"]["serverInfo"]["name"] == "weatherflow"
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {
        "weatherflow.submit_run",
        "weatherflow.get_run",
        "weatherflow.timeline",
        "weatherflow.list_approvals",
        "weatherflow.decide_approval",
    } <= names
    assert repeated["result"]["structuredContent"]["run"]["id"] == run_id
    assert status["result"]["structuredContent"]["run"]["user_intent"] == ("Explain WeatherFlow")
    assert len(await container.runs.list_recent()) == 1


async def test_unknown_method_and_tool_return_json_rpc_errors(tmp_path: Path) -> None:
    server = WeatherFlowMCPServer(await RuntimeContainer.create(Settings(data_dir=tmp_path)))

    method = await server.handle({"jsonrpc": "2.0", "id": 1, "method": "missing", "params": {}})
    tool = await call(server, 2, "weatherflow.missing", {})

    assert method["error"]["code"] == -32601
    assert tool["error"]["code"] == -32602

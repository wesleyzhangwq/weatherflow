import argparse
import asyncio
import getpass
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from weatherflow import __version__
from weatherflow.bootstrap import RuntimeContainer
from weatherflow.config import Settings


def build_parser() -> argparse.ArgumentParser:
    settings = Settings()
    parser = argparse.ArgumentParser(prog="weatherflow")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Run the local WeatherFlow daemon")
    serve.add_argument("--host", default=settings.host)
    serve.add_argument("--port", type=int, default=settings.port)
    serve.add_argument("--reload", action="store_true")

    subparsers.add_parser("mcp-server", help="Run the WeatherFlow stdio MCP server")

    configure_minimax = subparsers.add_parser(
        "configure-minimax",
        help="Validate and store a MiniMax API key in the macOS Keychain",
    )
    configure_minimax.add_argument("--model", default="MiniMax-M2.7")
    configure_minimax.add_argument("--base-url", default="https://api.minimax.io/v1")
    configure_minimax.add_argument("--api-key-stdin", action="store_true")
    subparsers.add_parser("model-status", help="Show non-secret model configuration status")

    run = subparsers.add_parser("run", help="Create and execute a durable Run")
    run.add_argument("intent")
    run.add_argument("--client-request-id")
    run.add_argument("--workspace-id")
    run.add_argument("--no-execute", action="store_true")

    status_command = subparsers.add_parser("status", help="Read a Run")
    status_command.add_argument("run_id")

    timeline = subparsers.add_parser("timeline", help="Read a Run timeline")
    timeline.add_argument("run_id")

    for decision in ("approve", "deny"):
        command = subparsers.add_parser(decision, help=f"{decision.title()} an Action")
        command.add_argument("approval_id")
        command.add_argument("--expected-version", type=int, default=0)
        command.add_argument("--rationale")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.command is None:
        parser.error("a command is required")

    if args.command == "serve":
        settings = Settings(host=args.host, port=args.port, data_dir=args.data_dir)
        uvicorn.run(
            "weatherflow.api.app:app",
            host=settings.host,
            port=settings.port,
            reload=args.reload,
            log_level=settings.log_level.lower(),
        )
        return 0
    return asyncio.run(_run_command(args))


async def _run_command(args: argparse.Namespace) -> int:
    container = await RuntimeContainer.create(Settings(data_dir=args.data_dir))
    if args.command == "configure-minimax":
        api_key = (
            sys.stdin.readline().strip()
            if args.api_key_stdin
            else getpass.getpass("MiniMax API key (stored in macOS Keychain): ").strip()
        )
        if not api_key:
            return 2
        configuration = await container.configure_minimax(
            api_key=api_key,
            model=args.model,
            base_url=args.base_url,
        )
        print(configuration.model_dump_json(exclude={"credential_ref"}))
        return 0
    if args.command == "model-status":
        status = await container.model_configurations.status(container.default_workspace.id)
        print(status.model_dump_json())
        return 0
    if args.command == "mcp-server":
        from weatherflow.mcp.server import serve_stdio

        await serve_stdio(container)
        return 0
    if args.command == "run":
        run, _ = await container.submit_run(
            user_intent=args.intent,
            client_request_id=args.client_request_id,
            workspace_id=args.workspace_id,
            execute=not args.no_execute,
        )
        stored = await container.runs.get(run.id)
        if stored is None:
            return 1
        print(stored.model_dump_json())
        return 0
    if args.command == "status":
        run = await container.runs.get(args.run_id)
        if run is None:
            return 1
        print(run.model_dump_json())
        return 0
    if args.command == "timeline":
        events = await container.ledger.list_correlation(args.run_id, limit=1000)
        print(json.dumps([event.model_dump(mode="json") for event in events]))
        return 0
    if args.command in {"approve", "deny"}:
        bundle = await container.approval_coordinator.decide(
            approval_id=args.approval_id,
            expected_version=args.expected_version,
            approved=args.command == "approve",
            decided_by="user",
            rationale=args.rationale,
        )
        await container.resume_run(bundle.run.id)
        print(bundle.model_dump_json())
        return 0
    return 1

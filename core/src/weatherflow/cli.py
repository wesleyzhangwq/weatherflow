import argparse
from collections.abc import Sequence

import uvicorn

from weatherflow import __version__
from weatherflow.config import Settings


def build_parser() -> argparse.ArgumentParser:
    settings = Settings()
    parser = argparse.ArgumentParser(prog="weatherflow")
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Run the local WeatherFlow daemon")
    serve.add_argument("--host", default=settings.host)
    serve.add_argument("--port", type=int, default=settings.port)
    serve.add_argument("--reload", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.command != "serve":
        parser.error("a command is required")

    settings = Settings(host=args.host, port=args.port)
    uvicorn.run(
        "weatherflow.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )
    return 0

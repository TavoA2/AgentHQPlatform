"""Operational CLI. Sprint 1 adds `create-admin` and migration helpers."""

import argparse
import sys

import uvicorn

# Psycopg's async mode cannot run on Windows' default ProactorEventLoop.
LOOP = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-hq")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run(
            "agent_hq.main:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
            loop=LOOP,
            log_config=None,
        )

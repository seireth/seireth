"""Cross-platform development commands for Seireth."""

from __future__ import annotations

import argparse
import subprocess
import sys
from .config import settings
from .verify import verify


def run(command: list[str]) -> int:
    return subprocess.call([sys.executable, "-m", *command])


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="Run Seireth development commands.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Start the development API server")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    test = subparsers.add_parser("test", help="Run the test suite")
    test.add_argument("pytest_args", nargs=argparse.REMAINDER)

    check = subparsers.add_parser("verify", help="Run the MVP-0 API workflow")
    check.add_argument("--base-url", default=None)
    check.add_argument("--api-key")

    args = parser.parse_args()
    if args.command == "serve":
        return run([
            "uvicorn",
            "app.main:app",
            "--reload",
            "--host",
            args.host if args.host is not None else settings.api_host,
            "--port",
            str(args.port if args.port is not None else settings.api_port),
        ])
    if args.command == "test":
        return run(["pytest", *args.pytest_args])
    try:
        import json
        print(json.dumps(
            verify(
                args.base_url if args.base_url is not None else settings.api_base_url,
                args.api_key if args.api_key is not None else settings.api_key,
            ),
            indent=2,
            default=str,
        ))
    except Exception as error:
        print(f"verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Cross-platform development commands for Seireth."""

from __future__ import annotations

import argparse
import subprocess
import sys

from .config import settings
from .verify import positive_timeout, verify


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
    check.add_argument("--timeout-seconds", type=positive_timeout, default=120)
    check.add_argument("--expected-backend", choices=("inmemory", "docker"))

    args = parser.parse_args()
    if args.command == "serve":
        return run(
            [
                "uvicorn",
                "app.main:app",
                "--reload",
                "--host",
                args.host if args.host is not None else settings.api_host,
                "--port",
                str(args.port if args.port is not None else settings.api_port),
            ]
        )
    if args.command == "test":
        return run(["pytest", *args.pytest_args])
    try:
        import json

        print(
            json.dumps(
                verify(
                    args.base_url
                    if args.base_url is not None
                    else settings.api_base_url,
                    timeout_seconds=args.timeout_seconds,
                    expected_backend=args.expected_backend,
                ),
                indent=2,
                default=str,
            )
        )
    except Exception as error:
        print(f"verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

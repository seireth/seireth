"""Cross-platform development commands for Seireth."""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys

from .verify import positive_timeout, verify


def run(command: list[str]) -> int:
    return subprocess.call([sys.executable, "-m", *command])


def _docker_up(timeout_seconds: float) -> int:
    compose_env = os.environ.copy()
    for stage, command in (
        ("build", ["build", "api"]),
        ("stop API", ["stop", "api"]),
        ("start PostgreSQL", ["up", "-d", "--wait", "postgres"]),
        ("migration", ["run", "--rm", "--no-deps", "-T", "migrate"]),
        (
            "API readiness",
            [
                "up",
                "-d",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                str(math.ceil(timeout_seconds)),
                "api",
            ],
        ),
    ):
        try:
            status = subprocess.call(["docker", "compose", *command], env=compose_env)
            if stage == "build" and not status:
                stage = "Docker socket permissions"
                socket_group = subprocess.check_output(
                    [
                        "docker",
                        "compose",
                        "run",
                        "--rm",
                        "--no-deps",
                        "-T",
                        "--volume",
                        "/var/run/docker.sock:/var/run/docker.sock",
                        "migrate",
                        "stat",
                        "-c",
                        "%g",
                        "/var/run/docker.sock",
                    ],
                    env=compose_env,
                    text=True,
                ).strip()
                if not socket_group.isascii() or not socket_group.isdecimal():
                    raise ValueError("Docker socket group must be a numeric GID")
                compose_env["SEIRETH_DOCKER_SOCKET_GID"] = socket_group
        except (OSError, subprocess.CalledProcessError, ValueError) as error:
            print(f"docker-up failed during {stage}: {error}", file=sys.stderr)
            return 1
        if status:
            print(
                f"docker-up failed during {stage}. Inspect with: docker compose ps -a; docker compose logs api",
                file=sys.stderr,
            )
            return status
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="Run Seireth development commands.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Start the development API server")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    subparsers.add_parser("test", help="Run pytest, forwarding all following arguments")

    check = subparsers.add_parser("verify", help="Run the MVP-0 API workflow")
    check.add_argument("--base-url", default=None)
    check.add_argument("--timeout-seconds", type=positive_timeout, default=120)
    check.add_argument("--expected-backend", choices=("inmemory", "docker"))

    subparsers.add_parser("migrate", help="Apply versioned database migrations")
    docker_up = subparsers.add_parser(
        "docker-up", help="Build, migrate, and start the Docker stack"
    )
    docker_up.add_argument(
        "--api-ready-timeout-seconds", type=positive_timeout, default=120
    )

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        return run(["pytest", *sys.argv[2:]])
    args = parser.parse_args()
    if args.command == "docker-up":
        return _docker_up(args.api_ready_timeout_seconds)
    if args.command == "migrate":
        from .migration import migrate

        migrate()
        return 0
    from .config import settings

    if args.command == "serve":
        return run(
            [
                "uvicorn",
                "app.api:app",
                "--reload",
                "--host",
                args.host if args.host is not None else settings.api_host,
                "--port",
                str(args.port if args.port is not None else settings.api_port),
            ]
        )
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

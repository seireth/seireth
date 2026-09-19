"""Real API processes: native simulated execution and opt-in Docker recovery."""

import os
import socket
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from time import monotonic, sleep

import httpx
import pytest

from app import models
from app.config import settings

docker_only = pytest.mark.skipif(
    os.environ.get("SEIRETH_DOCKER_TESTS") != "1",
    reason="Set SEIRETH_DOCKER_TESTS=1 to run real Docker tests",
)


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=20).strip()


def wait_until(check, seconds=30):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        value = check()
        if value:
            return value
        sleep(0.05)
    raise AssertionError("Timed out waiting for Docker lifecycle")


@pytest.mark.parametrize(
    "backend,action",
    [
        ("inmemory", "verify"),
        pytest.param("docker", "cancel", marks=docker_only),
        pytest.param("docker", "crash", marks=docker_only),
    ],
)
def test_real_api_lifecycle(database, tmp_path, backend, action):
    # Reserve an ephemeral local port, then launch a separate actual API process.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "SEIRETH_DATABASE_URL": settings.database_url,
        "SEIRETH_SANDBOX_BACKEND": backend,
    }
    if backend == "inmemory":
        env["PATH"] = str(Path(sys.executable).parent)  # Docker must not be needed.
    processes = []
    log = (tmp_path / "api.log").open("w+")

    def start():
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        processes.append(process)

        def ready():
            if process.poll() is not None:
                log.seek(0)
                raise AssertionError(log.read())
            try:
                return client.get("/health").status_code == 200
            except httpx.TransportError:
                return False

        wait_until(ready)
        return process

    aid = None
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
        try:
            process = start()
            if backend == "inmemory":
                from app.verify import verify

                result = verify(str(client.base_url), expected_backend="inmemory")
                assert result["results"]["status"] == "completed"
                assert result["results"]["result"]["finding_count"] == 3
                return

            def post(path, data):
                response = client.post(path, json=data)
                response.raise_for_status()
                return response.json()

            project = post("/api/v1/projects", {"name": "Docker recovery"})
            target = post(
                "/api/v1/targets",
                {
                    "project_id": project["id"],
                    "name": "slow",
                    "url": "http://demo-target:8080/slow",
                },
            )
            scope = post(
                "/api/v1/authorization-scopes",
                {
                    "project_id": project["id"],
                    "target_id": target["id"],
                    "allowed_url": "http://demo-target:8080/slow",
                    "expires_at": (models.now() + timedelta(minutes=5)).isoformat(),
                },
            )
            assessment = post(
                "/api/v1/assessments",
                {
                    "project_id": project["id"],
                    "target_id": target["id"],
                    "scope_id": scope["id"],
                },
            )
            aid = assessment["id"]
            selector = f"label=seireth.assessment={aid}"
            wait_until(
                lambda: (
                    "seireth-assessment-runner-"
                    in docker("ps", "--filter", selector, "--format", "{{.Names}}")
                )
            )
            if action == "crash":
                process.kill()
                process.wait(timeout=10)
                start()
            else:
                response = client.post(f"/api/v1/assessments/{aid}/cancel")
                assert response.status_code == 202
                assert response.json()["status"] == "cancelling"

            def terminal():
                report = client.get(f"/api/v1/assessments/{aid}/results").json()
                return (
                    report
                    if report["status"] in {"completed", "cancelled", "failed"}
                    else None
                )

            report = wait_until(terminal, 60)
            assert report["status"] == (
                "completed" if action == "crash" else "cancelled"
            ), report
            assert report["result"]["cleanup_verified"]
            assert report["result"]["attempt"] == (2 if action == "crash" else 1)
            assert len(report["findings"]) == (3 if action == "crash" else 0)
            assert not docker(
                "ps", "-a", "--filter", selector, "--format", "{{.Names}}"
            )
            assert not docker(
                "network", "ls", "--filter", selector, "--format", "{{.Name}}"
            )
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
            log.close()
            if aid:
                # Remove only resources carrying this test's exact assessment label.
                for identity in docker(
                    "ps", "-aq", "--filter", f"label=seireth.assessment={aid}"
                ).splitlines():
                    docker("rm", "-f", identity)
                for identity in docker(
                    "network", "ls", "-q", "--filter", f"label=seireth.assessment={aid}"
                ).splitlines():
                    docker("network", "rm", identity)

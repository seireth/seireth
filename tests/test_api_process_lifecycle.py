"""Real API processes: native simulated execution and opt-in Docker recovery."""

import os
import socket
import subprocess
import sys
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import models
from app.config import settings
from app.verify import verify

docker_only = pytest.mark.skipif(
    os.environ.get("SEIRETH_DOCKER_TESTS") != "1",
    reason="Set SEIRETH_DOCKER_TESTS=1 to run real Docker tests",
)


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=20).strip()


@pytest.fixture
def api_process(database, tmp_path, request, wait_until):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    backend = request.param
    env = {
        **os.environ,
        "SEIRETH_DATABASE_URL": settings.database_url,
        "SEIRETH_SANDBOX_BACKEND": backend,
    }
    if backend == "inmemory":
        env["PATH"] = str(Path(sys.executable).parent)  # Docker must not be needed.
    api = SimpleNamespace(backend=backend, assessment_id=None, process=None)
    with ExitStack() as cleanup:
        log = cleanup.enter_context((tmp_path / "api.log").open("w+"))
        api.client = cleanup.enter_context(
            httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5)
        )

        def remove_resources():
            if api.assessment_id:
                selector = f"label=seireth.assessment={api.assessment_id}"
                for identity in docker("ps", "-aq", "--filter", selector).splitlines():
                    docker("rm", "-f", identity)
                for identity in docker(
                    "network", "ls", "-q", "--filter", selector
                ).splitlines():
                    docker("network", "rm", identity)

        cleanup.callback(remove_resources)

        def stop(process):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            assert process.poll() is not None

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
            cleanup.callback(stop, process)
            api.process = process

            def ready():
                if process.poll() is not None:
                    raise AssertionError(
                        f"API process exited with {process.returncode}"
                    )
                try:
                    return api.client.get("/health").status_code == 200
                except httpx.TransportError:
                    return False

            try:
                wait_until(
                    ready, description="API readiness", timeout=30, interval=0.05
                )
            except AssertionError as error:
                log.seek(0)
                raise AssertionError(f"{error}\n{log.read()}") from error

        api.start = start
        start()
        yield api


@pytest.mark.parametrize(
    "api_process,action,expected_status,expected_attempt,expected_findings",
    [
        ("inmemory", "verify", "completed", 1, 3),
        pytest.param(
            "docker",
            "cancel",
            "cancelled",
            1,
            0,
            marks=[docker_only, pytest.mark.docker],
        ),
        pytest.param(
            "docker",
            "crash",
            "completed",
            2,
            3,
            marks=[docker_only, pytest.mark.docker],
        ),
    ],
    indirect=["api_process"],
)
def test_real_api_lifecycle(
    api_process,
    action,
    expected_status,
    expected_attempt,
    expected_findings,
    wait_until,
):
    client = api_process.client
    if api_process.backend == "inmemory":
        result = verify(str(client.base_url), expected_backend="inmemory")
        assert result["results"]["status"] == expected_status
        assert result["results"]["result"]["finding_count"] == expected_findings
        assert result["results"]["result"]["attempt"] == expected_attempt
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
            "plugins": ["security-headers"],
        },
    )
    aid = api_process.assessment_id = assessment["id"]
    assert assessment["plugins"] == ["security-headers"]
    selector = f"label=seireth.assessment={aid}"
    wait_until(
        lambda: (
            "seireth-assessment-runner-"
            in docker("ps", "--filter", selector, "--format", "{{.Names}}")
        ),
        description="Docker runner startup",
        timeout=30,
        interval=0.05,
    )
    if action == "crash":
        api_process.process.kill()
        api_process.process.wait(timeout=10)
        api_process.start()
    else:
        response = client.post(f"/api/v1/assessments/{aid}/cancel")
        assert response.status_code == 202
        assert response.json()["status"] == "cancelling"

    report = wait_until(
        lambda: client.get(f"/api/v1/assessments/{aid}/results").json(),
        lambda report: report["status"] in {"completed", "cancelled", "failed"},
        description="Docker assessment completion",
        timeout=60,
        interval=0.05,
    )
    assert report["status"] == expected_status, report
    assert report["result"]["cleanup_verified"]
    assert report["result"]["attempt"] == expected_attempt
    assert client.get(f"/api/v1/assessments/{aid}").json()["plugins"] == [
        "security-headers"
    ]
    if action == "crash":
        assert report["result"]["plugins"] == [
            {"id": "security-headers", "finding_count": 3}
        ]
    assert len(report["findings"]) == expected_findings
    assert not docker("ps", "-a", "--filter", selector, "--format", "{{.Names}}")
    assert not docker("network", "ls", "--filter", selector, "--format", "{{.Name}}")

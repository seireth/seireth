"""A containerized API restart cannot mistake reused PID 1 for the old process."""

import json
import os
import subprocess
from uuid import uuid4

import httpx
import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("SEIRETH_DOCKER_TESTS") != "1",
        reason="requires prepared API and demo images",
    ),
]


def docker(*args, env=None):
    return subprocess.check_output(
        ["docker", *args], text=True, timeout=30, env=env
    ).strip()


def test_containerized_website_recovery_proves_old_process_exit(
    tmp_path, wait_until, postgres_image
):
    token = uuid4().hex[:16]
    network, postgres, website, api = [
        f"seireth-process-{kind}-{token}"
        for kind in ("network", "postgres", "website", "api")
    ]
    image = os.environ.get(
        "SEIRETH_TEST_API_IMAGE",
        os.environ.get("COMPOSE_PROJECT_NAME", "seireth") + "-app:local",
    )
    created = []
    environment = {**os.environ, "POSTGRES_PASSWORD": "controlled-process-db"}
    try:
        docker("network", "create", network)
        created.append(("network", network))
        docker(
            "run",
            "-d",
            "--name",
            postgres,
            "--network",
            network,
            "--network-alias=db",
            "--tmpfs=/var/lib/postgresql",
            "-e",
            "POSTGRES_PASSWORD",
            postgres_image,
            env=environment,
        )
        created.append(("container", postgres))
        wait_until(
            lambda: (
                subprocess.run(
                    ["docker", "exec", postgres, "pg_isready", "-U", "postgres"],
                    capture_output=True,
                ).returncode
                == 0
            ),
            description="container recovery PostgreSQL",
            timeout=30,
        )
        docker(
            "run",
            "-d",
            "--name",
            website,
            "--network",
            network,
            "--network-alias=website",
            "seireth/demo-app:local",
        )
        created.append(("container", website))
        subnet = json.loads(docker("network", "inspect", network))[0]["IPAM"]["Config"][
            0
        ]["Subnet"]
        config = tmp_path / "operator.json"
        config.write_text(
            json.dumps(
                {
                    "networks": {
                        "fixture": {"url": "http://website:8080/", "cidrs": [subnet]}
                    }
                }
            )
        )
        # This synthetic public grant must be readable by the image's UID 65532,
        # including on hosts whose default file permissions are owner-only.
        config.chmod(0o644)
        environment.update(
            SEIRETH_DATABASE_URL="postgresql+psycopg://postgres:controlled-process-db@db:5432/postgres",
            SEIRETH_API_HOST="0.0.0.0",
            SEIRETH_API_PORT="8000",
        )
        env_args = [
            arg
            for name in (
                "SEIRETH_DATABASE_URL",
                "SEIRETH_API_HOST",
                "SEIRETH_API_PORT",
            )
            for arg in ("-e", name)
        ]
        docker(
            "run",
            "--rm",
            "--network",
            network,
            *env_args,
            image,
            "python",
            "-m",
            "app.cli.commands",
            "migrate",
            env=environment,
        )
        group = docker(
            "run",
            "--rm",
            "-v",
            "/var/run/docker.sock:/socket:ro",
            image,
            "stat",
            "-c",
            "%g",
            "/socket",
        )
        docker(
            "run",
            "-d",
            "--name",
            api,
            "--network",
            network,
            "--group-add",
            group,
            "-p",
            "127.0.0.1::8000",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "-v",
            f"{config.resolve()}:/operator.json:ro",
            "-e",
            "SEIRETH_OPERATOR_CONFIG_FILE=/operator.json",
            *env_args,
            image,
            env=environment,
        )
        created.append(("container", api))
        port = docker("port", api, "8000").rsplit(":", 1)[1]
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:

            def ready():
                try:
                    return client.get("/health").status_code == 200
                except httpx.HTTPError:
                    return False

            wait_until(ready, description="containerized API", timeout=30)
            project = client.post(
                "/api/v1/projects", json={"name": "process identity"}
            ).json()
            target_response = client.post(
                "/api/v1/targets",
                json={
                    "project_id": project["id"],
                    "name": "existing fixture",
                    "kind": "website",
                    "url": "http://website:8080/",
                    "network_profile": "fixture",
                },
            )
            assert target_response.status_code == 200, target_response.text
            target = target_response.json()
            response = client.post(
                "/api/v1/assessments",
                json={
                    "project_id": project["id"],
                    "target_id": target["id"],
                    "routes": [
                        {
                            "key": "root",
                            "url": "http://website:8080/lab/nosniff-first-invalid",
                            "plugins": ["http-security-headers"],
                        },
                        {
                            "key": "slow",
                            "url": "http://website:8080/slow",
                            "plugins": ["http-security-headers"],
                        },
                    ],
                },
            )
            assert response.status_code == 202, response.text
            identifier = response.json()["id"]

            def entered_slow_route():
                query = "SELECT count(*) FROM route_results WHERE assessment_id = %s"
                code = (
                    "import os,psycopg; c=psycopg.connect(os.environ['SEIRETH_DATABASE_URL'].replace('postgresql+psycopg:', 'postgresql:')); print(c.execute("
                    + repr(query)
                    + ", ("
                    + repr(identifier)
                    + ",)).fetchone()[0])"
                )
                return docker("exec", api, "python", "-c", code) == "1"

            wait_until(
                entered_slow_route,
                description="first website route committed",
                timeout=20,
                interval=0.05,
            )
            docker("kill", api)
            docker("start", api)
            client.base_url = (
                "http://127.0.0.1:" + docker("port", api, "8000").rsplit(":", 1)[1]
            )
            wait_until(ready, description="restarted container API", timeout=30)
            result = client.get(f"/api/v1/assessments/{identifier}/results").json()
            assert result["status"] == "failed", result
            assert not result["cleanup_pending"], result
            assert result["result"]["cleanup_verified"], result
            assert result["result"]["execution_outcome"] == "interrupted"
            assert result["result"]["attempt"] == 1
            assert len(result["findings"]) == 1
            assert (
                client.get(f"/api/v1/assessments/{identifier}/report").status_code
                == 200
            )
    finally:
        if ("container", api) in created:
            try:
                (tmp_path / "api.log").write_text(docker("logs", api), encoding="utf-8")
            except subprocess.SubprocessError:
                pass
        for kind, name in reversed(created):
            subprocess.run(
                ["docker", "rm", "-f", name]
                if kind == "container"
                else ["docker", "network", "rm", name],
                capture_output=True,
            )

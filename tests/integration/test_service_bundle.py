"""Real configured app/PostgreSQL bundle, shared routes, and owned-volume cleanup."""

import json
import os
import subprocess

import pytest

from app.core.config import settings
from tests.api.helpers import finish
from tests.integration.helpers import remove_assessment_resources

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("SEIRETH_DOCKER_TESTS") != "1",
        reason="requires prepared Docker images",
    ),
]


@pytest.mark.parametrize("mode", ["completed", "timeout", "startup-failure"])
def test_owned_postgres_bundle_and_verified_cleanup(
    client, project, tmp_path, monkeypatch, wait_until, mode
):
    path = tmp_path / "operator.json"
    path.write_text(
        json.dumps(
            {
                "secrets": {
                    "db": {"env": "FIXTURE_DB_PASSWORD"},
                    "session": {"env": "FIXTURE_SESSION"},
                },
                "requests": {
                    "session": {"secret_headers": {"Authorization": "session"}}
                },
                "launches": {
                    "fixture": {
                        "startup_seconds": 30,
                        "target": {
                            "depends_on": ["postgres"],
                            "secret_environment": {
                                "DATABASE_PASSWORD": "db",
                                "SESSION_TOKEN": "session",
                            },
                        },
                        "services": {
                            "postgres": {
                                "image": "postgres:18-trixie",
                                "uid": 999,
                                "gid": 999,
                                "environment": {
                                    "PGDATA": "/var/lib/postgresql/18/docker"
                                },
                                "secret_environment": {"POSTGRES_PASSWORD": "db"},
                                "tmpfs": ["/var/run/postgresql"],
                                "volumes": [
                                    {"name": "database", "path": "/var/lib/postgresql"}
                                ],
                                "readiness": {"kind": "tcp", "port": 5432},
                            }
                        },
                    }
                },
            }
        )
    )
    monkeypatch.setattr(settings, "operator_config_file", str(path))
    monkeypatch.setenv("FIXTURE_DB_PASSWORD", "fixture-db-secret")
    monkeypatch.setenv("FIXTURE_SESSION", "Bearer fixture-session-secret")
    if mode == "startup-failure":
        config = json.loads(path.read_text())
        config["launches"]["fixture"]["startup_seconds"] = 3
        config["launches"]["fixture"]["target"]["readiness"] = {
            "kind": "tcp",
            "port": 1,
        }
        path.write_text(json.dumps(config))
    target_response = client.post(
        "/api/v1/targets",
        json={
            "project_id": project,
            "name": "bundle",
            "image": "seireth/service-fixture:local",
            "url": "http://fixture.test:8080/",
            "launch_profile": "fixture",
        },
    )
    assert target_response.status_code == 200, target_response.text
    target = target_response.json()
    routes = [
        {
            "key": "private",
            "url": target["url"] + "private",
            "plugins": ["http-security-headers", "csp-policy", "cookie-security"],
            "request_profile": "session",
        }
    ]
    if mode == "timeout":
        routes.append(
            {
                "key": "slow",
                "url": target["url"] + "slow",
                "plugins": ["http-security-headers"],
                "request_seconds": 0.1,
            }
        )
    response = client.post(
        "/api/v1/assessments",
        json={"project_id": project, "target_id": target["id"], "routes": routes},
    )
    assert response.status_code == 202, response.text
    identifier = response.json()["id"]
    try:
        result, report = finish(client, identifier, wait_until)
        assert result["status"] == ("completed" if mode == "completed" else "failed"), (
            result
        )
        assert result["result"]["cleanup_verified"] and not result["cleanup_pending"], (
            result
        )
        assert result["result"]["verdict"]["status"] == (
            "pass" if mode == "completed" else "blocked"
        ), result
        assert "fixture-session-secret" not in json.dumps(report)
        assert "fixture-db-secret" not in json.dumps(report)
        selector = f"label=seireth.assessment={identifier}"
        for args in (["ps", "-aq"], ["network", "ls", "-q"], ["volume", "ls", "-q"]):
            assert (
                subprocess.check_output(
                    ["docker", *args, "--filter", selector], text=True
                ).strip()
                == ""
            )
    finally:
        remove_assessment_resources(identifier)

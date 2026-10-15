"""Real API processes and opt-in Docker lifecycle acceptance."""

import os
from dataclasses import replace
from uuid import uuid4

import pytest

from app.persistence import models
from tests.api.helpers import finish
from tests.integration.helpers import (
    docker,
    remove_assessment_resources,
    submit_docker_assessment,
)

docker_only = pytest.mark.skipif(
    os.environ.get("SEIRETH_DOCKER_TESTS") != "1",
    reason="Set SEIRETH_DOCKER_TESTS=1 to run real Docker tests",
)


@pytest.mark.parametrize(
    "api_process,action,expected_status,expected_attempt,expected_findings",
    [
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
        pytest.param(
            "docker",
            "image-removed",
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

    image = "seireth/demo-app:local"
    if action == "image-removed":
        image = f"seireth/recovery-test:{uuid4().hex}"
        docker("tag", "seireth/demo-app:local", image)
    _, assessment = submit_docker_assessment(
        client, "/slow", ["http-security-headers"], image=image
    )
    aid = api_process.assessment_id = assessment["id"]
    assert assessment["plugins"] == ["http-security-headers"]
    selector = f"label=seireth.assessment={aid}"
    wait_until(
        lambda: (
            "seireth-runner-"
            in docker("ps", "--filter", selector, "--format", "{{.Names}}")
        ),
        description="Docker runner startup",
        timeout=30,
        interval=0.05,
    )
    # Verified cancellation and recovery require recorded resource identities.
    # Interrupting an in-flight create may correctly leave cleanup pending.
    wait_until(
        lambda: (
            "seireth-target-"
            in docker("ps", "--filter", selector, "--format", "{{.Names}}")
        ),
        description="Docker target startup after identity persistence",
        timeout=30,
        interval=0.05,
    )
    if action in {"crash", "image-removed"}:
        api_process.process.kill()
        api_process.process.wait(timeout=10)
        if action == "image-removed":
            docker("image", "rm", image)
        api_process.start()
    else:
        response = client.post(f"/api/v1/assessments/{aid}/cancel")
        assert response.status_code == 202
        assert response.json()["status"] == "cancelling"

    report = wait_until(
        lambda: client.get(f"/api/v1/assessments/{aid}/results").json(),
        lambda report: report["status"] in {"completed", "cancelled", "failed"},
        description="Docker assessment completion",
        timeout=assessment["plan_snapshot"]["timeout_seconds"]
        + 2 * assessment["plan_snapshot"]["cleanup_seconds"]
        + 10,
        interval=0.05,
    )
    assert report["status"] == expected_status, (
        report["result"].get("error"),
        report["result"].get("cleanup_reason"),
        report["result"].get("routes"),
    )
    assert report["result"]["cleanup_verified"]
    assert report["result"]["attempt"] == expected_attempt
    if action == "image-removed":
        # Removing the submitted tag does not remove the pinned image content.
        assert "error" not in report["result"]
        assert not report["cleanup_pending"]
    assert client.get(f"/api/v1/assessments/{aid}").json()["plugins"] == [
        "http-security-headers"
    ]
    if action == "crash":
        assert [
            {key: plugin[key] for key in ("id", "finding_count")}
            for plugin in report["result"]["routes"][0]["plugins"]
        ] == [{"id": "http-security-headers", "finding_count": 3}]
    assert len(report["findings"]) == expected_findings
    assert not docker("ps", "-a", "--filter", selector, "--format", "{{.Names}}")
    assert not docker("network", "ls", "--filter", selector, "--format", "{{.Name}}")


@docker_only
@pytest.mark.docker
@pytest.mark.parametrize("case", ["vulnerable", "corrected", "plugin-failure"])
def test_acceptance_run_persists_provenance_and_survives_restart(
    database, monkeypatch, wait_until, make_plugin, case
):
    from datetime import datetime

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.assessments import plans as assessment_plans
    from app.assessments import worker
    from app.assessments import workflows as assessment_workflows
    from app.main import app
    from app.plugins.registry import PluginRegistry, registry

    analysis_calls = []

    def broken(_observation, _analysis):
        analysis_calls.append("broken")
        raise RuntimeError("synthetic crash detail")

    plugins = registry.plugins + (make_plugin("broken", broken),)
    selection = PluginRegistry(plugins)
    monkeypatch.setattr(assessment_plans, "registry", selection)
    monkeypatch.setattr(assessment_workflows, "registry", selection)
    path = (
        "/lab/nosniff-first-invalid"
        if case == "vulnerable"
        else "/lab/nosniff-first-valid"
    )
    selected = ["http-security-headers"] + (
        ["broken"] if case == "plugin-failure" else []
    )
    expected_status = "failed" if case == "plugin-failure" else "completed"
    aid = None
    try:
        with TestClient(app) as client:
            target, assessment = submit_docker_assessment(client, path, selected)
            aid = assessment["id"]
            for _ in range(5):
                worker.dispatcher.submit(aid)
            result, report = finish(client, aid, wait_until)
            assert result["status"] == expected_status, result["result"]
            assert (
                result["result"]["cleanup_verified"] and not result["cleanup_pending"]
            )
            assert len(result["findings"]) == (1 if case == "vulnerable" else 0)
            if case == "vulnerable":
                assert (
                    result["findings"][0]["title"]
                    == "Missing or ineffective X-Content-Type-Options"
                )
            if case == "plugin-failure":
                assert result["result"]["error_kind"] == "plugin_error"
                assert result["result"]["failed_plugin"] == "broken"
                assert analysis_calls == ["broken"]
                assert "synthetic crash detail" not in str(result)
            execution = result["result"]["execution"]
            assert execution["target"] == target
            assert execution["plugins"] == [
                {"id": identity, "version": "1.0.0"} for identity in selected
            ]
            assert (
                datetime.fromisoformat(execution["deadline_at"])
                - datetime.fromisoformat(execution["started_at"])
            ).total_seconds() == assessment["plan_snapshot"]["timeout_seconds"]
            with database.SessionLocal() as db:
                attempts = list(
                    db.scalars(
                        select(models.Attempt).where(
                            models.Attempt.assessment_id == aid
                        )
                    )
                )
                assert len(attempts) == 1
                assert attempts[0].execution_metadata == execution
                assert attempts[0].cleanup_verified
                assert all(
                    entry["state"] in {"removed", "not_requested"}
                    for entry in attempts[0].operation_journal["resources"].values()
                )
            assert {entry["finding_id"] for entry in report["evidence"]} == {
                finding["id"] for finding in report["findings"]
            }
        # A fresh API/dispatcher reads the same results, even if installed plugins change.
        newer = PluginRegistry(
            tuple(
                replace(
                    plugin,
                    manifest=plugin.manifest.model_copy(update={"version": "9.0.0"}),
                )
                for plugin in plugins
            )
        )
        monkeypatch.setattr(assessment_plans, "registry", newer)
        monkeypatch.setattr(assessment_workflows, "registry", newer)
        with TestClient(app) as client:
            refreshed = client.get(f"/api/v1/assessments/{aid}/report").json()
            refreshed.pop("generated_at")
            report.pop("generated_at")
            assert refreshed == report
            assert (
                client.get(f"/api/v1/assessments/{aid}").json()["status"]
                == expected_status
            )
        selector = f"label=seireth.assessment={aid}"
        assert not docker("ps", "-aq", "--filter", selector)
        assert not docker("network", "ls", "-q", "--filter", selector)
    finally:
        remove_assessment_resources(aid)


@docker_only
@pytest.mark.docker
@pytest.mark.parametrize("api_process", ["docker"], indirect=True)
def test_real_cookie_assessment_preserves_repeated_fields_and_verifies_cleanup(
    api_process, database, wait_until, tmp_path
):
    from sqlalchemy import select

    client = api_process.client

    selection = ["http-security-headers", "cookie-security"]
    _, assessment = submit_docker_assessment(client, "/cookies", selection)
    aid = api_process.assessment_id = assessment["id"]
    report = wait_until(
        lambda: client.get(f"/api/v1/assessments/{aid}/results").json(),
        lambda report: report["status"] in {"completed", "cancelled", "failed"},
        description="real cookie assessment completion",
        timeout=60,
        interval=0.05,
    )
    assert report["status"] == "completed", report
    assert [
        {key: plugin[key] for key in ("id", "finding_count")}
        for plugin in report["result"]["routes"][0]["plugins"]
    ] == [{"id": plugin, "finding_count": 3} for plugin in selection]
    assert report["result"]["finding_count"] == len(report["findings"]) == 6
    assert report["result"]["cleanup_verified"] and not report["cleanup_pending"]
    with database.SessionLocal() as db:
        evidence = list(
            db.scalars(
                select(models.Evidence)
                .join(models.Finding)
                .where(models.Finding.assessment_id == aid)
            )
        )
        assert len(evidence) == 6
        assert {item.finding_id for item in evidence} == {
            item["id"] for item in report["findings"]
        }
        assert {
            item.data["cookie_name"]
            for item in evidence
            if item.data["header"] == "set-cookie"
        } == {"cross_site", "__Secure-demo", "__Host-demo"}
    evidence_response = client.get(f"/api/v1/assessments/{aid}/evidence")
    assert evidence_response.status_code == 200
    returned = evidence_response.json()
    assert returned["status"] == "completed" and not returned["cleanup_pending"]
    assert len(returned["evidence"]) == 6
    assert {item["finding_id"]: item["data"] for item in returned["evidence"]} == {
        item.finding_id: item.data for item in evidence
    }
    for secret in (
        "synthetic-theme",
        "synthetic-cross-site",
        "synthetic-secure-prefix",
        "synthetic-host-prefix",
    ):
        assert secret not in str(report)
        assert secret not in evidence_response.text
        assert secret not in str([item.data for item in evidence])
        assert secret not in (tmp_path / "api.log").read_text()
    selector = f"label=seireth.assessment={aid}"
    assert not docker("ps", "-a", "--filter", selector, "--format", "{{.Names}}")
    assert not docker("network", "ls", "--filter", selector, "--format", "{{.Name}}")

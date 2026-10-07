"""Reject wrong evidence and incomplete cleanup, including zero-finding cases."""

import json
import sys
from copy import deepcopy

import httpx
import pytest

from examples.demo_app import verify as demo_verify
from examples.demo_app.scenarios import BY_PATH, IMAGE, ORIGIN
from examples.demo_app.verify import validate_outcome
from tests.header_evidence import header_evidence


def outcome(path):
    scenario = BY_PATH[path]
    results = {
        "assessment_id": "assessment-1",
        "status": "completed",
        "cleanup_pending": False,
        "result": {
            "sandbox_backend": "docker",
            "cleanup_verified": True,
            "finding_count": len(scenario.expected),
            "response": {
                "status_code": scenario.status,
                "media_type": scenario.media_type,
            },
            "plugins": [
                {
                    "id": "http-security-headers",
                    "finding_count": len(scenario.expected),
                    "checks": [
                        {
                            "rule_id": rule,
                            "status": status,
                            "reason": "Independent expected fixture outcome.",
                        }
                        for rule, status in zip(
                            (
                                "x-content-type-options",
                                "content-security-policy",
                                "framing-protection",
                            ),
                            scenario.expected_checks,
                        )
                    ],
                }
            ],
        },
        "findings": [
            {
                "id": f"finding-{index}",
                "plugin": "http-security-headers",
                "remediation": "Configure this response header.",
            }
            for index, _ in enumerate(scenario.expected)
        ],
    }
    evidence = {
        "assessment_id": "assessment-1",
        "status": "completed",
        "cleanup_pending": False,
        "evidence": [
            {
                "id": f"evidence-{index}",
                "finding_id": f"finding-{index}",
                "kind": "http-response",
                "data": header_evidence(
                    header,
                    url=ORIGIN + path,
                    status_code=scenario.status,
                    media_type=scenario.media_type,
                ),
            }
            for index, header in enumerate(scenario.expected)
        ],
    }
    return scenario, results, evidence


@pytest.mark.parametrize("path", ["/", "/lab/missing-all", "/login"])
def test_exact_expected_outcomes_are_accepted(path):
    scenario, results, evidence = outcome(path)
    assert validate_outcome(scenario, "assessment-1", results, evidence) == evidence


@pytest.mark.parametrize(
    "failure",
    [
        "simulated",
        "pending",
        "cleanup",
        "wrong-rule",
        "wrong-status",
        "wrong-media",
        "wrong-evidence-status",
        "wrong-evidence-media",
        "wrong-check",
        "wrong-url",
        "wrong-finding",
        "wrong-count",
        "missing-evidence",
        "unsafe-evidence",
        "no-remediation",
    ],
)
def test_invalid_live_outcome_is_rejected(failure):
    scenario, results, evidence = outcome("/lab/missing-all")
    results, evidence = deepcopy(results), deepcopy(evidence)
    if failure == "simulated":
        results["result"]["sandbox_backend"] = "inmemory"
    elif failure == "pending":
        results["cleanup_pending"] = True
    elif failure == "cleanup":
        results["result"]["cleanup_verified"] = False
    elif failure == "wrong-rule":
        evidence["evidence"][0]["data"]["rule_id"] = "content-security-policy"
    elif failure == "wrong-status":
        results["result"]["response"]["status_code"] = 404
    elif failure == "wrong-media":
        results["result"]["response"]["media_type"] = "application/json"
    elif failure == "wrong-evidence-status":
        evidence["evidence"][0]["data"]["status_code"] = 404
    elif failure == "wrong-evidence-media":
        evidence["evidence"][0]["data"]["media_type"] = "application/json"
    elif failure == "wrong-check":
        results["result"]["plugins"][0]["checks"][0]["status"] = "passed"
    elif failure == "wrong-url":
        evidence["evidence"][0]["data"]["url"] = ORIGIN + "/account"
    elif failure == "wrong-finding":
        evidence["evidence"][0]["finding_id"] = "other-finding"
    elif failure == "wrong-count":
        results["result"]["finding_count"] = 2
    elif failure == "missing-evidence":
        evidence["evidence"].pop()
    elif failure == "unsafe-evidence":
        evidence["evidence"][0]["data"]["cookie_value"] = "synthetic-secret"
    elif failure == "no-remediation":
        results["findings"][0]["remediation"] = " "
    with pytest.raises(RuntimeError) as error:
        validate_outcome(scenario, "assessment-1", results, evidence)
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("register_only", [False, True])
def test_verifier_requires_completed_assessments_and_checks_resources(
    monkeypatch, register_only
):
    paths = ("/", "/lab/missing-all")
    actions = ["project.created"]
    current_path = [None]
    checked_resources = []

    def respond(request):
        path = request.url.path
        if path == "/api/v1/runtime":
            return httpx.Response(
                200,
                json={"sandbox_backend": "docker"},
            )
        if path == "/api/v1/projects":
            return httpx.Response(200, json={"id": "project-1"})
        if path == "/api/v1/targets":
            payload = json.loads(request.content)
            assert payload["image"] == IMAGE
            assert payload["url"] == ORIGIN
            actions.append("target.registered")
            return httpx.Response(200, json={"id": "target-1"})
        if path == "/api/v1/assessments":
            payload = json.loads(request.content)
            assert payload["plugins"] == ["http-security-headers"]
            current_path[0] = payload["url"].removeprefix(ORIGIN)
            actions.extend(
                ("assessment.queued", "assessment.running", "assessment.completed")
            )
            return httpx.Response(202, json={"id": "assessment-1"})
        if path.endswith("/results"):
            return httpx.Response(200, json=outcome(current_path[0])[1])
        if path.endswith("/evidence"):
            return httpx.Response(200, json=outcome(current_path[0])[2])
        if path.endswith("/audit-events"):
            return httpx.Response(200, json=[{"action": action} for action in actions])
        raise AssertionError(f"Unexpected request: {request.method} {path}")

    original_client = httpx.Client
    monkeypatch.setattr(
        demo_verify.httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs
        ),
    )
    monkeypatch.setattr(
        demo_verify, "verify_resource_removal", checked_resources.append
    )
    report = demo_verify.verify(
        "http://test",
        scenarios=tuple(BY_PATH[path] for path in paths),
        register_only=register_only,
    )
    assert len(report["cases"]) == 2
    assert report["project_url"] == "http://test/dashboard/projects/project-1"
    assert report["passed"] is (None if register_only else True)
    assert len(checked_resources) == (0 if register_only else 2)


@pytest.mark.parametrize(
    "runtime",
    [
        {"sandbox_backend": "inmemory"},
    ],
)
def test_unusable_runtime_is_rejected_before_creating_any_records(monkeypatch, runtime):
    observed = []

    def respond(request):
        observed.append((request.method, request.url.path))
        return httpx.Response(200, json=runtime)

    original_client = httpx.Client
    monkeypatch.setattr(
        demo_verify.httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs
        ),
    )
    with pytest.raises(RuntimeError, match="Docker backend"):
        demo_verify.verify("http://test")
    assert observed == [("GET", "/api/v1/runtime")]


@pytest.mark.parametrize("resources", ["", "remaining-resource-id"])
def test_independent_resource_queries_use_the_assessment_label(monkeypatch, resources):
    queries = []

    def query(command, **kwargs):
        queries.append(command)
        return resources

    monkeypatch.setattr(demo_verify.subprocess, "check_output", query)
    if resources:
        with pytest.raises(RuntimeError, match="Docker resources remain"):
            demo_verify.verify_resource_removal("assessment-1")
    else:
        demo_verify.verify_resource_removal("assessment-1")
        assert len(queries) == 2
    assert all(
        command[-1] == "label=seireth.assessment=assessment-1" for command in queries
    )


def test_cli_reports_verification_failure_with_nonzero_exit(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["demo-app"])

    def fail(base_url, **kwargs):
        raise RuntimeError("synthetic unavailable API")

    monkeypatch.setattr(demo_verify, "verify", fail)
    assert demo_verify.main() == 1
    assert "synthetic unavailable API" in capsys.readouterr().err

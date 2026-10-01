"""Polling checks use a fake clock, avoiding slow and timing-dependent tests."""

import argparse

import httpx
import pytest

from app import verify


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(verify.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        verify.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds)
    )
    return now


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
def test_polling_waits_beyond_old_five_second_window(clock, terminal):
    def respond(request):
        status = terminal if clock[0] >= 6 else "running"
        return httpx.Response(200, json={"status": status, "result": None})

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        assert verify.wait_for_results(client, "assessment-1", 10)["status"] == terminal
    assert 6 <= clock[0] < 10


def test_polling_timeout_reports_id_and_last_state(clock):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "queued", "result": None})
    )
    with httpx.Client(base_url="http://test", transport=transport) as client:
        with pytest.raises(
            RuntimeError, match="assessment-1 did not finish within 1s.*queued"
        ):
            verify.wait_for_results(client, "assessment-1", 1)
    assert clock[0] == pytest.approx(1)


def test_polling_http_errors_are_not_hidden(clock):
    transport = httpx.MockTransport(lambda request: httpx.Response(403, text="denied"))
    with httpx.Client(base_url="http://test", transport=transport) as client:
        with pytest.raises(RuntimeError, match="403: denied"):
            verify.wait_for_results(client, "assessment-1", 1)


def test_request_timeout_includes_last_response(clock):
    def respond(request):
        if clock[0] == 0:
            return httpx.Response(200, json={"status": "running", "result": None})
        assert request.extensions["timeout"]["read"] <= 0.8
        raise httpx.ReadTimeout("slow server", request=request)

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        with pytest.raises(
            RuntimeError, match="assessment-1 polling request timed out.*running"
        ):
            verify.wait_for_results(client, "assessment-1", 1)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_timeout_is_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        verify.positive_timeout(value)


@pytest.mark.parametrize(
    "failure,message",
    [
        ("failed", "assessment did not produce findings"),
        ("empty", "assessment did not produce findings"),
        ("cleanup", "sandbox cleanup was not verified"),
        ("backend", "expected docker backend"),
        ("audit", "unexpected audit trail"),
        ("evidence-http", "500:.*stored evidence is invalid"),
        ("evidence-payload", "API returned invalid evidence"),
        ("evidence-assessment", "evidence did not match the completed assessment"),
        ("evidence-status", "evidence did not match the completed assessment"),
        ("evidence-cleanup", "evidence did not match the completed assessment"),
        ("evidence-empty", "evidence did not match the completed assessment"),
        ("evidence-finding", "evidence did not match the completed assessment"),
    ],
)
def test_verification_rejects_invalid_outcomes(monkeypatch, failure, message):
    results = {
        "status": "failed" if failure == "failed" else "completed",
        "findings": []
        if failure == "empty"
        else [{"id": "finding-1", "title": "example"}],
        "result": {
            "cleanup_verified": failure != "cleanup",
            "sandbox_backend": "inmemory",
        },
    }
    actions = [
        "project.created",
        "target.registered",
        "scope.authorized",
        "assessment.queued",
        "assessment.running",
        "assessment.completed",
    ]
    if failure == "audit":
        actions = actions[:-1]
    evidence = {
        "assessment_id": "other-assessment"
        if failure == "evidence-assessment"
        else "assessment-1",
        "status": "failed" if failure == "evidence-status" else "completed",
        "cleanup_pending": failure == "evidence-cleanup",
        "evidence": []
        if failure == "evidence-empty"
        else [
            {
                "id": "evidence-1",
                "finding_id": "other-finding"
                if failure == "evidence-finding"
                else "finding-1",
                "kind": "http-response",
                "data": {
                    "url": "http://demo-target:8080/",
                    "header": "content-security-policy",
                },
            }
        ],
    }
    if failure == "evidence-payload":
        evidence["evidence"][0]["data"]["cookie_value"] = (
            "synthetic-private-cookie-value"
        )
    routes = {
        ("GET", "/health"): (200, {"status": "ok"}),
        ("POST", "/api/v1/projects"): (200, {"id": "project-1"}),
        ("POST", "/api/v1/targets"): (200, {"id": "target-1"}),
        ("POST", "/api/v1/authorization-scopes"): (200, {"id": "scope-1"}),
        ("POST", "/api/v1/assessments"): (202, {"id": "assessment-1"}),
        ("GET", "/api/v1/assessments/assessment-1/results"): (200, results),
        ("GET", "/api/v1/assessments/assessment-1/evidence"): (
            (500, {"detail": "stored evidence is invalid"})
            if failure == "evidence-http"
            else (200, evidence)
        ),
        ("GET", "/api/v1/projects/project-1/audit-events"): (
            200,
            [{"action": action} for action in actions],
        ),
    }
    observed = []

    def respond(request):
        observed.append((request.method, request.url.path))
        status, body = routes[observed[-1]]
        return httpx.Response(status, json=body)

    client = httpx.Client
    monkeypatch.setattr(
        verify.httpx,
        "Client",
        lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs),
    )
    with pytest.raises(RuntimeError, match=message) as error:
        verify.verify(
            "http://test",
            expected_backend="docker" if failure == "backend" else "inmemory",
        )
    assert "synthetic-private-cookie-value" not in str(error.value)
    assert ("GET", "/api/v1/assessments/assessment-1/results") in observed
    assert (("GET", "/api/v1/projects/project-1/audit-events") in observed) is (
        failure == "audit"
    )
    assert (("GET", "/api/v1/assessments/assessment-1/evidence") in observed) is (
        failure == "audit" or failure.startswith("evidence-")
    )

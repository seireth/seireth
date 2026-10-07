"""Polling checks use a fake clock, avoiding slow and timing-dependent tests."""

import argparse
from unittest.mock import Mock

import httpx
import pytest

from app.cli import verify
from tests.header_evidence import header_evidence


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


@pytest.mark.parametrize("arrival", [1, 1.1])
def test_polling_rejects_completion_at_or_after_deadline(clock, arrival):
    def respond(request):
        clock[0] = arrival
        return httpx.Response(200, json={"status": "completed", "result": None})

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        with pytest.raises(
            RuntimeError, match="assessment-1 did not finish within 1s.*completed"
        ):
            verify.wait_for_results(client, "assessment-1", 1)
    assert clock[0] == arrival


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


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_direct_verification_rejects_invalid_timeout_before_http(monkeypatch, value):
    client = Mock()
    monkeypatch.setattr(verify.httpx, "Client", client)
    with pytest.raises(
        ValueError, match="timeout must be finite and greater than zero"
    ):
        verify.verify(
            "http://test",
            image="arbitrary:local",
            target_url="http://arbitrary:8080/",
            plugins=["http-security-headers"],
            timeout_seconds=value,
        )
    client.assert_not_called()


def test_verification_accepts_completed_zero_findings_with_explicit_target(monkeypatch):
    import json

    actions = [
        "project.created",
        "target.registered",
        "assessment.queued",
        "assessment.running",
        "assessment.completed",
    ]

    def respond(request):
        path = request.url.path
        if path == "/health":
            body = {"status": "ok"}
        elif path == "/api/v1/projects":
            body = {"id": "p"}
        elif path == "/api/v1/targets":
            payload = json.loads(request.content)
            assert payload["image"] == "another:local"
            assert payload["url"] == "http://another:8080/"
            body = {"id": "t", "url": payload["url"]}
        elif path == "/api/v1/assessments":
            assert json.loads(request.content) == {
                "project_id": "p",
                "target_id": "t",
                "url": "http://another:8080/",
                "plugins": ["http-security-headers", "cookie-security"],
            }
            return httpx.Response(202, json={"id": "a"})
        elif path.endswith("/results"):
            body = {
                "status": "completed",
                "findings": [],
                "result": {"cleanup_verified": True, "sandbox_backend": "docker"},
            }
        elif path.endswith("/evidence"):
            body = {
                "assessment_id": "a",
                "status": "completed",
                "cleanup_pending": False,
                "evidence": [],
            }
        elif path.endswith("/audit-events"):
            body = [{"action": action} for action in actions]
        else:
            pytest.fail(f"Unexpected request: {path}")
        return httpx.Response(200, json=body)

    original = httpx.Client
    monkeypatch.setattr(
        verify.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    report = verify.verify(
        "http://test",
        image="another:local",
        target_url="http://another:8080/",
        plugins=["http-security-headers", "cookie-security"],
        expected_backend="docker",
    )
    assert report["results"]["findings"] == []
    assert report["evidence"]["evidence"] == []


@pytest.mark.parametrize(
    "failure,message",
    [
        ("failed", "assessment did not complete"),
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
                "data": header_evidence(),
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
        ("POST", "/api/v1/targets"): (
            200,
            {"id": "target-1", "url": "http://arbitrary:8080/"},
        ),
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
        if request.method == "POST" and request.url.path == "/api/v1/targets":
            import json

            assert json.loads(request.content)["image"] == "arbitrary:local"
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
            image="arbitrary:local",
            target_url="http://arbitrary:8080/",
            plugins=["http-security-headers"],
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

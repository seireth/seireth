import pytest
from sqlalchemy import select

from app.persistence import models
from tests.api.helpers import snapshot, submission


def test_assessment_url_must_stay_within_target(client, project, target):
    response = client.post(
        "/api/v1/assessments",
        json={
            "project_id": project,
            "target_id": target["id"],
            "url": "http://other-app:8080/",
            "plugins": ["security-headers"],
        },
    )
    assert response.status_code == 403


def test_passive_assessment_returns_json_and_cleanup(
    client, project, assessment_payload, wait_until, database
):
    result = client.post(
        "/api/v1/assessments",
        json=assessment_payload,
    )
    assert result.status_code == 202
    assert result.headers["location"].endswith(result.json()["id"])
    assert result.json()["plugins"] == ["security-headers"]
    report = wait_until(
        lambda: client.get(f"/api/v1/assessments/{result.json()['id']}/results").json(),
        lambda report: report["status"] in {"completed", "failed", "cancelled"},
        description="assessment results",
    )
    assert report["status"] == "completed"
    assert report["result"]["cleanup_verified"] is True
    assert report["cleanup_pending"] is False
    assert report["result"]["cleanup_reason"] is None
    assert "plugin" not in report["result"]
    assert report["result"]["plugins"] == [
        {"id": "security-headers", "finding_count": 3}
    ]
    assert report["result"]["finding_count"] == 3
    assert len(report["findings"]) == report["result"]["finding_count"] == 3
    assert all(
        finding["plugin"] == "security-headers" for finding in report["findings"]
    )
    assert all(finding["remediation"] for finding in report["findings"])
    with database.SessionLocal() as db:
        findings = list(
            db.scalars(
                select(models.Finding).where(
                    models.Finding.assessment_id == report["assessment_id"]
                )
            )
        )
        evidence = list(
            db.scalars(
                select(models.Evidence)
                .join(models.Finding)
                .where(models.Finding.assessment_id == report["assessment_id"])
            )
        )
        assert len(findings) == len(evidence) == 3
        assert {item.finding_id for item in evidence} == {item.id for item in findings}
        assert {finding.id for finding in findings} == {
            finding["id"] for finding in report["findings"]
        }
        for stored in findings:
            returned = next(
                item for item in report["findings"] if item["id"] == stored.id
            )
            fields = ("plugin", "title", "severity", "description", "remediation")
            assert set(returned) == {"id", *fields}
            assert {field: getattr(stored, field) for field in fields} == {
                field: returned[field] for field in fields
            }
        assert {item.kind for item in evidence} == {"http-response"}
        assert {item.data["header"] for item in evidence} == {
            "x-content-type-options",
            "content-security-policy",
            "x-frame-options",
        }
        assert all(
            item.data == {"header": item.data["header"], "url": "http://demo-app:8080/"}
            for item in evidence
        )
    assessment = (client.get(result.headers["location"])).json()
    assert assessment["status"] == "completed"
    assert assessment["cleanup_pending"] is False
    assert assessment["result"] == report["result"]
    audit = (client.get(f"/api/v1/projects/{project}/audit-events")).json()
    assert [event["action"] for event in audit] == [
        "project.created",
        "target.registered",
        "assessment.queued",
        "assessment.running",
        "assessment.completed",
    ]


def test_queued_and_cancelled_before_execution_have_no_result(
    client, assessment_payload, monkeypatch
):
    from app.assessments.worker import dispatcher

    submitted = []
    monkeypatch.setattr(dispatcher, "submit", submitted.append)
    response = client.post(
        "/api/v1/assessments",
        json=assessment_payload,
    )
    assert response.status_code == 202
    queued = response.json()
    assert submitted == [queued["id"]]
    assert queued["status"] == "queued"
    assert queued["result"] is None
    location = response.headers["location"]
    assert (client.get(location)).json() == queued
    assert (client.get(location + "/results")).json()["result"] is None
    assert (client.post(location + "/cancel")).status_code == 200
    cancelled = (client.get(location + "/results")).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["result"] is None


@pytest.mark.parametrize(
    "plugins",
    [
        ["security-headers"],
        ["cookie-security"],
        ["security-headers", "cookie-security"],
        ["cookie-security", "security-headers"],
    ],
)
def test_cookie_assessments_preserve_selection_counts_and_redacted_evidence(
    client, assessment_payload, monkeypatch, database, wait_until, caplog, plugins
):
    from app.assessments.sandbox import InMemorySandbox
    from app.plugins.base import HttpObservation

    secret = "cookie-secret-not-for-storage"
    calls = []

    def response(self, url):
        calls.append(url)
        return HttpObservation(
            url=url,
            headers={
                "Set-Cookie": [
                    f"theme={secret}; SameSite=Lax",
                    f"cross={secret}; SameSite=None",
                    f"__Secure-session={secret}",
                    f"__Host-session={secret}; Secure; Domain={secret}; Path=/{secret}",
                ]
            },
        )

    monkeypatch.setattr(InMemorySandbox, "execute", response)
    submitted = client.post(
        "/api/v1/assessments", json={**assessment_payload, "plugins": plugins}
    )
    assert submitted.status_code == 202
    assert submitted.json()["plugins"] == plugins
    location = submitted.headers["location"]
    report = wait_until(
        lambda: client.get(location + "/results").json(),
        lambda report: report["status"] in {"completed", "failed", "cancelled"},
        description="cookie assessment completion",
    )
    assert report["status"] == "completed", report
    assert report["result"]["plugins"] == [
        {"id": plugin, "finding_count": 3} for plugin in plugins
    ]
    assert (
        report["result"]["finding_count"] == len(report["findings"]) == 3 * len(plugins)
    )
    assert {item["plugin"] for item in report["findings"]} == set(plugins)
    assert report["result"]["cleanup_verified"] and not report["cleanup_pending"]
    assert client.get(location).json()["plugins"] == plugins
    assert len(calls) == 1
    assert secret not in str(report)
    with database.SessionLocal() as db:
        evidence = list(
            db.scalars(
                select(models.Evidence)
                .join(models.Finding)
                .where(models.Finding.assessment_id == report["assessment_id"])
            )
        )
        assert len(evidence) == 3 * len(plugins)
        assert {item.finding_id for item in evidence} == {
            item["id"] for item in report["findings"]
        }
        assert secret not in str([item.data for item in evidence])
        if "cookie-security" in plugins:
            assert {
                item.data["rule"]
                for item in evidence
                if item.data["header"] == "set-cookie"
            } == {
                "samesite-none-without-secure",
                "secure-prefix",
                "host-prefix",
            }
    assert secret not in caplog.text
    returned = client.get(location + "/evidence")
    assert returned.status_code == 200
    entries = returned.json()["evidence"]
    assert len(entries) == len(report["findings"])
    assert [item["id"] for item in entries] == sorted(item["id"] for item in entries)
    assert secret not in returned.text
    assert {item["finding_id"]: item["data"] for item in entries} == {
        item.finding_id: item.data for item in evidence
    }


@pytest.fixture
def evidence_row(database):
    def create(assessment_id, *, identity=None, kind="http-response", data=None):
        with database.SessionLocal() as db:
            evidence = models.Evidence(
                kind=kind,
                data=data
                if data is not None
                else {
                    "url": "http://demo-app:8080/",
                    "header": "content-security-policy",
                },
            )
            if identity is not None:
                evidence.id = identity
            finding = models.Finding(
                assessment_id=assessment_id,
                plugin="security-headers",
                title="Test finding",
                severity="medium",
                description="Test evidence retrieval",
                remediation="Configure the inspected response header.",
                evidence=[evidence],
            )
            db.add(finding)
            db.commit()
            return finding.id, evidence.id

    return create


def test_evidence_retrieval_is_ordered_read_only_and_assessment_specific(
    client, database, assessment_graph, evidence_row, dispatch_calls
):
    first = assessment_graph(status="completed")
    second = assessment_graph(status="completed")
    z_finding, z_id = evidence_row(first.assessment.id, identity="z-evidence")
    a_finding, a_id = evidence_row(first.assessment.id, identity="a-evidence")
    evidence_row(second.assessment.id, identity="other-assessment-evidence")
    before = snapshot(database)
    path = f"/api/v1/assessments/{first.assessment.id}/evidence"
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {
        "assessment_id": first.assessment.id,
        "status": "completed",
        "cleanup_pending": False,
        "evidence": [
            {
                "id": identity,
                "finding_id": finding,
                "kind": "http-response",
                "data": {
                    "url": "http://demo-app:8080/",
                    "header": "content-security-policy",
                },
            }
            for finding, identity in [(a_finding, a_id), (z_finding, z_id)]
        ],
    }
    assert client.get(path).json() == response.json()
    assert snapshot(database) == before
    assert dispatch_calls == {"submit": [], "cancel": []}


@pytest.mark.parametrize("status", [item.value for item in models.AssessmentStatus])
def test_evidence_empty_states(
    client, database, assessment_graph, evidence_row, status
):
    graph = assessment_graph(status=status)
    if status != "completed":
        # Even a stray stored row must not be published before successful finalization.
        evidence_row(graph.assessment.id)
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, graph.assessment.id)
        item.cleanup_pending = status == "failed"
        db.commit()
    response = client.get(f"/api/v1/assessments/{graph.assessment.id}/evidence")
    assert response.status_code == 200
    assert response.json() == {
        "assessment_id": graph.assessment.id,
        "status": status,
        "cleanup_pending": status == "failed",
        "evidence": [],
    }


def test_unknown_assessment_evidence_returns_not_found(client):
    response = client.get("/api/v1/assessments/missing/evidence")
    assert response.status_code == 404
    assert response.json() == {"detail": "assessment not found"}


@pytest.mark.parametrize(
    "kind,data",
    [
        ("unsupported-kind", {"secret": "synthetic-evidence-secret"}),
        (
            "http-response",
            {
                "url": "http://demo-app:8080/",
                "header": "x-frame-options",
                "cookie_value": "synthetic-evidence-secret",
            },
        ),
        ("http-response", {"header": "synthetic-evidence-secret"}),
        (
            "http-response",
            {"url": "ftp://synthetic-evidence-secret/", "header": "x-frame-options"},
        ),
        (
            "http-response",
            {"url": "http://demo-app:8080/", "header": "synthetic-evidence-secret"},
        ),
        (
            "http-response",
            {
                "url": "http://demo-app:8080/",
                "header": "set-cookie",
                "cookie_name": "cross",
                "rule": "samesite-none-without-secure",
                "samesite": "none",
                "secure": "synthetic-evidence-secret",
            },
        ),
        ("http-response", ["synthetic-evidence-secret"]),
    ],
)
def test_invalid_stored_evidence_fails_without_partial_response_or_secret_diagnostics(
    client, database, assessment_graph, evidence_row, caplog, kind, data
):
    graph = assessment_graph(status="completed")
    evidence_row(graph.assessment.id, identity="a-valid-evidence")
    _, identity = evidence_row(
        graph.assessment.id, identity="z-invalid-evidence", kind=kind, data=data
    )
    before = snapshot(database)
    response = client.get(f"/api/v1/assessments/{graph.assessment.id}/evidence")
    assert response.status_code == 500
    assert response.json() == {"detail": "stored evidence is invalid"}
    assert "synthetic-evidence-secret" not in response.text
    assert "synthetic-evidence-secret" not in caplog.text
    assert identity in caplog.text and graph.assessment.id in caplog.text
    assert snapshot(database) == before


@pytest.mark.parametrize("target", ["https://demo-app:8080/"], indirect=True)
def test_repeated_cookies_and_multiple_rules_keep_their_exact_finding_links(
    client, assessment_payload, monkeypatch, wait_until, database
):
    from app.assessments.sandbox import InMemorySandbox
    from app.plugins.base import HttpObservation

    secret = "synthetic-repeated-cookie-secret"
    monkeypatch.setattr(
        InMemorySandbox,
        "execute",
        lambda self, url: HttpObservation(
            url=url,
            headers={
                "Set-Cookie": [
                    f"__hOsT-session={secret}; SameSite=None",
                    f"__hOsT-session={secret}; Secure; Path=/",
                    f"__hOsT-session={secret}; Secure; Path=/app",
                ]
            },
        ),
    )
    submitted = client.post(
        "/api/v1/assessments",
        json={**assessment_payload, "plugins": ["cookie-security"]},
    )
    assert submitted.status_code == 202
    location = submitted.headers["location"]
    report = wait_until(
        lambda: client.get(location + "/results").json(),
        lambda report: report["status"] in {"completed", "failed"},
        description="repeated cookie assessment",
    )
    assert report["status"] == "completed"
    assert len(report["findings"]) == 3
    response = client.get(location + "/evidence")
    assert response.status_code == 200
    returned = response.json()["evidence"]
    assert len(returned) == 3
    assert secret not in response.text
    assert {item["finding_id"] for item in returned} == {
        item["id"] for item in report["findings"]
    }
    with database.SessionLocal() as db:
        for entry in returned:
            finding = db.get(models.Finding, entry["finding_id"])
            assert entry["data"]["cookie_name"] == "__hOsT-session"
            if entry["data"]["rule"] == "samesite-none-without-secure":
                assert finding.title == "SameSite=None cookie lacks Secure"
            else:
                assert finding.title == "Invalid __Host- cookie configuration"
            assert finding.evidence[0].id == entry["id"]
            assert finding.evidence[0].data == entry["data"]


@pytest.mark.parametrize(
    "plugins, status",
    [
        (None, 422),
        ([], 422),
        (["unknown"], 400),
        (["security-headers", "security-headers"], 400),
    ],
)
def test_invalid_plugin_selection_is_rejected(
    client, assessment_payload, plugins, status
):
    response = client.post(
        "/api/v1/assessments",
        json={**assessment_payload, "plugins": plugins},
    )
    assert response.status_code == status


def test_omitted_plugin_selection_is_rejected(client, assessment_payload):
    del assessment_payload["plugins"]
    response = client.post("/api/v1/assessments", json=assessment_payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "plugins"]


@pytest.mark.parametrize("field", ["project_id", "target_id"])
def test_assessment_rejects_cross_project_identifiers(
    client, database, assessment_graph, dispatch_calls, field
):
    first, second = assessment_graph(), assessment_graph()
    payload = submission(first)
    payload[field] = submission(second)[field]
    before = snapshot(database)
    response = client.post("/api/v1/assessments", json=payload)
    assert response.status_code == 403
    assert response.json()["detail"] == "target does not belong to this project"
    assert snapshot(database) == before
    assert dispatch_calls == {"submit": [], "cancel": []}


def test_repeated_active_cancellation_is_idempotent(
    client, database, assessment_graph, dispatch_calls
):
    graph = assessment_graph(status="running")
    path = f"/api/v1/assessments/{graph.assessment.id}/cancel"
    for _ in range(2):
        response = client.post(path)
        assert response.status_code == 202
        assert response.json()["status"] == "cancelling"
    with database.SessionLocal() as db:
        events = list(
            db.scalars(
                select(models.AuditEvent).where(
                    models.AuditEvent.resource_id == graph.assessment.id
                )
            )
        )
        assert [event.action for event in events] == ["assessment.cancelling"]
        assert db.get(models.Assessment, graph.assessment.id).status == "cancelling"
    assert dispatch_calls == {"submit": [], "cancel": [graph.assessment.id] * 2}


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_assessments_cannot_be_cancelled(
    client, database, assessment_graph, dispatch_calls, status
):
    graph = assessment_graph(status=status)
    before = snapshot(database)
    response = client.post(f"/api/v1/assessments/{graph.assessment.id}/cancel")
    assert response.status_code == 409
    assert response.json()["detail"] == "assessment is no longer cancellable"
    assert snapshot(database) == before
    assert dispatch_calls == {"submit": [], "cancel": []}


def test_assessment_ordering_breaks_timestamp_ties(
    read_client, database, assessment_graph
):
    graph = assessment_graph(status="completed")
    with database.SessionLocal() as db:
        current = db.get(models.Assessment, graph.assessment.id)
        for identity in ["z", "a"]:
            db.add(
                models.Assessment(
                    id=identity,
                    project_id=graph.project.id,
                    target_id=graph.target.id,
                    url=graph.assessment.url,
                    status="completed",
                    plugins=["security-headers"],
                    created_at=current.created_at,
                )
            )
        db.commit()
    for resource, identities in [
        ("assessments", [graph.assessment.id, "a", "z"]),
    ]:
        items = read_client.get(
            f"/api/v1/projects/{graph.project.id}/{resource}"
        ).json()["items"]
        assert [item["id"] for item in items] == sorted(identities)

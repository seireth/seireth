from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models
from app.api import app
from app.config import settings


@pytest.fixture
def client(database):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def project(client):
    response = client.post("/api/v1/projects", json={"name": "demo"})
    assert response.status_code == 200
    return response.json()["id"]


@pytest.fixture
def target(client, project, request):
    response = client.post(
        "/api/v1/targets",
        json={
            "project_id": project,
            "name": "demo",
            "url": getattr(request, "param", "http://demo-target:8080"),
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def scope_payload(project, target):
    return {
        "project_id": project,
        "target_id": target["id"],
        "allowed_url": target["url"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }


@pytest.fixture
def assessment_payload(client, scope_payload):
    response = client.post("/api/v1/authorization-scopes", json=scope_payload)
    assert response.status_code == 200
    return {
        "project_id": scope_payload["project_id"],
        "target_id": scope_payload["target_id"],
        "scope_id": response.json()["id"],
        "plugins": ["security-headers"],
    }


def test_scope_is_required(client, project, target):
    response = client.post(
        "/api/v1/assessments",
        json={
            "project_id": project,
            "target_id": target["id"],
            "scope_id": "missing",
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
                select(models.Evidence).where(
                    models.Evidence.assessment_id == report["assessment_id"]
                )
            )
        )
        assert len(findings) == len(evidence) == 3
        assert {finding.id for finding in findings} == {
            finding["id"] for finding in report["findings"]
        }
        for stored in findings:
            returned = next(
                item for item in report["findings"] if item["id"] == stored.id
            )
            fields = ("plugin", "title", "severity", "description", "remediation")
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
            item.data
            == {"header": item.data["header"], "url": "http://demo-target:8080/"}
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
        "scope.authorized",
        "assessment.queued",
        "assessment.running",
        "assessment.completed",
    ]


def test_expired_scope_is_rejected(client, scope_payload):
    scope_payload["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    response = client.post("/api/v1/authorization-scopes", json=scope_payload)
    assert response.status_code == 400


def test_target_image_must_be_allowlisted(client, project):
    response = client.post(
        "/api/v1/targets",
        json={
            "project_id": project,
            "name": "untrusted",
            "image": "attacker/image:latest",
            "url": "http://demo-target:8080",
        },
    )
    assert response.status_code == 400


def test_target_and_scope_reject_urls_too_long_for_storage(client, project, target):
    grows_when_normalized = "https://example.test?" + "a" * (
        500 - len("https://example.test?")
    )
    response = client.post(
        "/api/v1/targets",
        json={"project_id": project, "name": "oversized", "url": grows_when_normalized},
    )
    assert response.status_code == 422

    response = client.post(
        "/api/v1/authorization-scopes",
        json={
            "project_id": project,
            "target_id": target["id"],
            "allowed_url": "http://demo-target:8080/" + "a" * 501,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("explicit_image", [False, True])
def test_target_stores_default_or_explicit_allowed_image(
    client, project, monkeypatch, explicit_image
):
    from app.db import SessionLocal
    from app.models import Target

    alternative = "seireth/alternative:local"
    monkeypatch.setattr(
        settings,
        "docker_allowed_target_images",
        [settings.docker_target_image, alternative],
    )
    payload = {"project_id": project, "name": "allowed"}
    if explicit_image:
        payload["image"] = alternative
    response = client.post("/api/v1/targets", json=payload)
    assert response.status_code == 200
    with SessionLocal() as db:
        target = db.get(Target, response.json()["id"])
        assert target.image == (
            alternative if explicit_image else settings.docker_target_image
        )


def test_default_image_must_also_be_allowlisted(client, project, monkeypatch):
    monkeypatch.setattr(settings, "docker_allowed_target_images", [])
    response = client.post(
        "/api/v1/targets", json={"project_id": project, "name": "default"}
    )
    assert response.status_code == 400


def test_queued_and_cancelled_before_execution_have_no_result(
    client, assessment_payload, monkeypatch
):
    from app.api import dispatcher

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


def test_plugin_catalog_and_explicit_selection(client, assessment_payload, monkeypatch):
    from app.api import dispatcher

    catalog = (client.get("/api/v1/plugins")).json()
    assert [item["id"] for item in catalog] == ["security-headers", "cookie-security"]
    assert all(set(item) == {"id", "name", "description"} for item in catalog)
    assert all(item["name"].strip() and item["description"].strip() for item in catalog)
    monkeypatch.setattr(dispatcher, "submit", lambda assessment_id: None)
    response = client.post(
        "/api/v1/assessments",
        json={**assessment_payload, "plugins": ["security-headers"]},
    )
    assert response.status_code == 202
    assert response.json()["plugins"] == ["security-headers"]
    stored = (client.get(response.headers["location"])).json()
    assert stored["plugins"] == ["security-headers"]


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
    from app.plugins.base import HttpObservation
    from app.sandbox import InMemorySandbox

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
                select(models.Evidence).where(
                    models.Evidence.assessment_id == report["assessment_id"]
                )
            )
        )
        assert len(evidence) == 3 * len(plugins)
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


@pytest.mark.parametrize("target", ["https://example.test/app"], indirect=True)
@pytest.mark.parametrize(
    "allowed_url",
    [
        pytest.param("https://other.example/app", id="different-origin"),
        pytest.param("https://example.test/application", id="path-prefix"),
        pytest.param("https://example.test/app/../secret", id="parent-path"),
    ],
)
def test_scope_cannot_escape_target_origin_or_path(client, scope_payload, allowed_url):
    response = client.post(
        "/api/v1/authorization-scopes",
        json={**scope_payload, "allowed_url": allowed_url},
    )
    assert response.status_code == 400


@pytest.fixture
def dispatch_calls(client, monkeypatch):
    from app.api import dispatcher

    calls = {"submit": [], "cancel": []}
    for method, recorded in calls.items():
        monkeypatch.setattr(dispatcher, method, recorded.append)
    return calls


def snapshot(database):
    with database.engine.connect() as connection:
        return {
            table.name: [
                dict(row)
                for row in connection.execute(
                    select(table).order_by(table.c.id)
                ).mappings()
            ]
            for table in database.Base.metadata.sorted_tables
        }


def submission(graph):
    return {
        "project_id": graph.project.id,
        "target_id": graph.target.id,
        "scope_id": graph.scope.id,
        "plugins": ["security-headers"],
    }


@pytest.mark.parametrize(
    "operation", ["target", "scope", "assessment", "read", "results", "cancel", "audit"]
)
def test_foreign_project_access_is_denied_without_side_effects(
    client, database, assessment_graph, dispatch_calls, operation
):
    graph = assessment_graph(owner="other-actor", status="completed")
    aid, pid = graph.assessment.id, graph.project.id
    requests = {
        "target": ("post", "/api/v1/targets", {"project_id": pid, "name": "foreign"}),
        "scope": (
            "post",
            "/api/v1/authorization-scopes",
            {
                "project_id": pid,
                "target_id": graph.target.id,
                "allowed_url": graph.target.url,
                "expires_at": graph.scope.expires_at.isoformat(),
            },
        ),
        "assessment": ("post", "/api/v1/assessments", submission(graph)),
        "read": ("get", f"/api/v1/assessments/{aid}", None),
        "results": ("get", f"/api/v1/assessments/{aid}/results", None),
        "cancel": ("post", f"/api/v1/assessments/{aid}/cancel", None),
        "audit": ("get", f"/api/v1/projects/{pid}/audit-events", None),
    }
    before = snapshot(database)
    method, path, payload = requests[operation]
    response = client.request(method, path, json=payload)
    assert response.status_code == 403
    assert response.json()["detail"] == "project access denied"
    assert snapshot(database) == before
    assert dispatch_calls == {"submit": [], "cancel": []}


@pytest.mark.parametrize("field", ["project_id", "target_id", "scope_id"])
def test_assessment_rejects_cross_project_identifiers(
    client, database, assessment_graph, dispatch_calls, field
):
    first, second = assessment_graph(), assessment_graph()
    payload = submission(first)
    payload[field] = submission(second)[field]
    before = snapshot(database)
    response = client.post("/api/v1/assessments", json=payload)
    assert response.status_code == 403
    assert response.json()["detail"] == "valid authorization scope required"
    assert snapshot(database) == before
    assert dispatch_calls == {"submit": [], "cancel": []}


@pytest.mark.parametrize("missing", [False, True])
def test_scope_rejects_missing_or_cross_project_target(
    client, database, assessment_graph, dispatch_calls, missing
):
    first, second = assessment_graph(), assessment_graph()
    before = snapshot(database)
    response = client.post(
        "/api/v1/authorization-scopes",
        json={
            "project_id": first.project.id,
            "target_id": "missing" if missing else second.target.id,
            "allowed_url": first.target.url,
            "expires_at": first.scope.expires_at.isoformat(),
        },
    )
    assert response.status_code == 400
    assert snapshot(database) == before
    assert dispatch_calls == {"submit": [], "cancel": []}


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/assessments/missing"),
        ("get", "/api/v1/assessments/missing/results"),
        ("post", "/api/v1/assessments/missing/cancel"),
        ("get", "/api/v1/projects/missing/audit-events"),
        ("post", "/api/v1/targets"),
        ("post", "/api/v1/authorization-scopes"),
        ("post", "/api/v1/assessments"),
    ],
)
def test_missing_resources_return_404_without_side_effects(
    client, database, dispatch_calls, method, path
):
    payload = (
        {
            "project_id": "missing",
            "target_id": "missing",
            "allowed_url": "http://demo-target:8080/",
            "expires_at": "2099-01-01T00:00:00Z",
        }
        if "authorization-scopes" in path
        else {"project_id": "missing", "name": "missing"}
    )
    if path == "/api/v1/assessments":
        payload = {
            "project_id": "missing",
            "target_id": "missing",
            "scope_id": "missing",
            "plugins": ["security-headers"],
        }
    before = snapshot(database)
    response = client.request(method, path, json=payload if method == "post" else None)
    assert response.status_code == 404
    assert snapshot(database) == before
    assert dispatch_calls == {"submit": [], "cancel": []}


def test_health_returns_503_when_dispatcher_unavailable(client, monkeypatch):
    from app.api import dispatcher

    monkeypatch.setattr(dispatcher, "_executor", None)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["detail"] == "assessment dispatcher unavailable"


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

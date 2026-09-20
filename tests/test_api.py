import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

from app.api import app
from app.config import settings

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(database):
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as test_client,
    ):
        yield test_client


@pytest_asyncio.fixture
async def project(client):
    response = await client.post("/api/v1/projects", json={"name": "demo"})
    assert response.status_code == 200
    return response.json()["id"]


@pytest_asyncio.fixture
async def target(client, project, request):
    response = await client.post(
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


@pytest_asyncio.fixture
async def assessment_payload(client, scope_payload):
    response = await client.post("/api/v1/authorization-scopes", json=scope_payload)
    assert response.status_code == 200
    return {
        "project_id": scope_payload["project_id"],
        "target_id": scope_payload["target_id"],
        "scope_id": response.json()["id"],
    }


async def test_scope_is_required(client, project, target):
    response = await client.post(
        "/api/v1/assessments",
        json={
            "project_id": project,
            "target_id": target["id"],
            "scope_id": "missing",
        },
    )
    assert response.status_code == 403


async def test_passive_assessment_returns_json_and_cleanup(
    client, project, assessment_payload
):
    result = await client.post(
        "/api/v1/assessments",
        json=assessment_payload,
    )
    assert result.status_code == 202
    assert result.headers["location"].endswith(result.json()["id"])
    assert result.json()["plugins"] == ["security-headers"]
    for _ in range(50):
        report = (
            await client.get(f"/api/v1/assessments/{result.json()['id']}/results")
        ).json()
        if report["status"] != "queued" and report["status"] != "running":
            break
        await asyncio.sleep(0.01)
    assert report["status"] == "completed"
    assert report["result"]["cleanup_verified"] is True
    assert report["cleanup_pending"] is False
    assert report["result"]["cleanup_reason"] is None
    assert "plugin" not in report["result"]
    assert report["result"]["plugins"] == [
        {"id": "security-headers", "finding_count": 3}
    ]
    assert report["result"]["finding_count"] == 3
    assert report["findings"]
    assert all(
        finding["plugin"] == "security-headers" for finding in report["findings"]
    )
    assert all(finding["remediation"] for finding in report["findings"])
    assessment = (await client.get(result.headers["location"])).json()
    assert assessment["status"] == "completed"
    assert assessment["cleanup_pending"] is False
    assert assessment["result"] == report["result"]
    audit = (await client.get(f"/api/v1/projects/{project}/audit-events")).json()
    assert [event["action"] for event in audit] == [
        "project.created",
        "target.registered",
        "scope.authorized",
        "assessment.queued",
        "assessment.running",
        "assessment.completed",
    ]


async def test_expired_scope_is_rejected(client, scope_payload):
    scope_payload["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    response = await client.post("/api/v1/authorization-scopes", json=scope_payload)
    assert response.status_code == 400


async def test_target_image_must_be_allowlisted(client, project):
    response = await client.post(
        "/api/v1/targets",
        json={
            "project_id": project,
            "name": "untrusted",
            "image": "attacker/image:latest",
            "url": "http://demo-target:8080",
        },
    )
    assert response.status_code == 400


@pytest.mark.parametrize("explicit_image", [False, True])
async def test_target_stores_default_or_explicit_allowed_image(
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
    response = await client.post("/api/v1/targets", json=payload)
    assert response.status_code == 200
    with SessionLocal() as db:
        target = db.get(Target, response.json()["id"])
        assert target.image == (
            alternative if explicit_image else settings.docker_target_image
        )


async def test_default_image_must_also_be_allowlisted(client, project, monkeypatch):
    monkeypatch.setattr(settings, "docker_allowed_target_images", [])
    response = await client.post(
        "/api/v1/targets", json={"project_id": project, "name": "default"}
    )
    assert response.status_code == 400


async def test_queued_and_cancelled_before_execution_have_no_result(
    client, assessment_payload, monkeypatch
):
    from app.api import dispatcher

    submitted = []
    monkeypatch.setattr(dispatcher, "submit", submitted.append)
    response = await client.post(
        "/api/v1/assessments",
        json=assessment_payload,
    )
    assert response.status_code == 202
    queued = response.json()
    assert submitted == [queued["id"]]
    assert queued["status"] == "queued"
    assert queued["result"] is None
    location = response.headers["location"]
    assert (await client.get(location)).json() == queued
    assert (await client.get(location + "/results")).json()["result"] is None
    assert (await client.post(location + "/cancel")).status_code == 200
    cancelled = (await client.get(location + "/results")).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["result"] is None


async def test_plugin_catalog_and_explicit_selection(
    client, assessment_payload, monkeypatch
):
    from app.api import dispatcher

    catalog = (await client.get("/api/v1/plugins")).json()
    assert catalog == [
        {
            "id": "security-headers",
            "name": "HTTP security headers",
            "description": "Check three browser security headers on the target response.",
            "profiles": ["passive"],
        }
    ]
    monkeypatch.setattr(dispatcher, "submit", lambda assessment_id: None)
    response = await client.post(
        "/api/v1/assessments",
        json={**assessment_payload, "plugins": ["security-headers"]},
    )
    assert response.status_code == 202
    assert response.json()["plugins"] == ["security-headers"]
    stored = (await client.get(response.headers["location"])).json()
    assert stored["plugins"] == ["security-headers"]


@pytest.mark.parametrize(
    "plugins", [[], ["unknown"], ["security-headers", "security-headers"]]
)
async def test_invalid_plugin_selection_is_rejected(
    client, assessment_payload, plugins
):
    response = await client.post(
        "/api/v1/assessments",
        json={**assessment_payload, "plugins": plugins},
    )
    assert response.status_code == 400


@pytest.mark.parametrize("target", ["https://example.test/app"], indirect=True)
async def test_scope_cannot_escape_target_origin_or_path(client, scope_payload):
    for allowed_url in (
        "https://other.example/app",
        "https://example.test/application",
        "https://example.test/app/../secret",
    ):
        response = await client.post(
            "/api/v1/authorization-scopes",
            json={**scope_payload, "allowed_url": allowed_url},
        )
        assert response.status_code == 400

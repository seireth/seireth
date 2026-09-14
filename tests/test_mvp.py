from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
import asyncio

from app.config import settings
from app.main import app


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_scope_is_required(client):
    project = (await client.post("/api/v1/projects", json={"name": "demo"})).json()
    target = (await client.post("/api/v1/targets", json={
        "project_id": project["id"],
        "name": "demo",
        "url": "http://demo-target:8080",
    })).json()
    response = await client.post("/api/v1/assessments", json={
        "project_id": project["id"],
        "target_id": target["id"],
        "scope_id": "missing",
    })
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_passive_assessment_returns_json_and_cleanup(client):
    project = (await client.post("/api/v1/projects", json={"name": "demo2"})).json()
    target = (await client.post("/api/v1/targets", json={
        "project_id": project["id"],
        "name": "demo",
        "url": "http://demo-target:8080",
    })).json()
    scope = (await client.post("/api/v1/authorization-scopes", json={
        "project_id": project["id"],
        "target_id": target["id"],
        "allowed_url": "http://demo-target:8080",
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat(),
    })).json()
    result = await client.post("/api/v1/assessments", json={
        "project_id": project["id"],
        "target_id": target["id"],
        "scope_id": scope["id"],
    })
    assert result.status_code == 202
    assert result.headers["location"].endswith(result.json()["id"])
    for _ in range(50):
        report = (
            await client.get(f"/api/v1/assessments/{result.json()['id']}/results")
        ).json()
        if report["status"] != "queued" and report["status"] != "running":
            break
        await asyncio.sleep(0.01)
    assert report["status"] == "completed"
    assert report["result"]["cleanup_verified"] is True
    assert report["findings"]
    audit = (
        await client.get(f"/api/v1/projects/{project['id']}/audit-events")
    ).json()
    assert [event["action"] for event in audit] == [
        "project.created",
        "target.registered",
        "scope.authorized",
        "assessment.queued",
        "assessment.completed",
    ]


@pytest.mark.asyncio
async def test_expired_scope_is_rejected(client):
    project = (await client.post("/api/v1/projects", json={"name": "expired"})).json()
    target = (await client.post("/api/v1/targets", json={
        "project_id": project["id"],
        "name": "demo",
        "url": "http://demo-target:8080",
    })).json()
    scope = await client.post("/api/v1/authorization-scopes", json={
        "project_id": project["id"],
        "target_id": target["id"],
        "allowed_url": "http://demo-target:8080",
        "expires_at": (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat(),
    })
    assert scope.status_code == 400


@pytest.mark.asyncio
async def test_configured_api_key_requires_bearer_token(client):
    original_key = settings.api_key
    settings.api_key = "test-key"
    try:
        response = await client.post(
            "/api/v1/projects",
            json={"name": "protected"},
        )
        assert response.status_code == 401
        response = await client.post(
            "/api/v1/projects",
            headers={"Authorization": "Bearer wrong-key"},
            json={"name": "protected"},
        )
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        response = await client.post(
            "/api/v1/projects",
            headers={"Authorization": "Bearer test-key"},
            json={"name": "protected"},
        )
        assert response.status_code == 200
    finally:
        settings.api_key = original_key


@pytest.mark.asyncio
async def test_project_resources_are_isolated_between_api_keys(client):
    original_key = settings.api_key
    settings.api_key = "owner-key"
    try:
        project = (
            await client.post(
                "/api/v1/projects",
                headers={"Authorization": "Bearer owner-key"},
                json={"name": "private"},
            )
        ).json()
        settings.api_key = "other-key"
        response = await client.get(
            f"/api/v1/projects/{project['id']}/audit-events",
            headers={"Authorization": "Bearer other-key"},
        )
        assert response.status_code == 403
    finally:
        settings.api_key = original_key


@pytest.mark.asyncio
async def test_target_image_must_be_allowlisted(client):
    project = (await client.post("/api/v1/projects", json={"name": "images"})).json()
    response = await client.post("/api/v1/targets", json={
        "project_id": project["id"],
        "name": "untrusted",
        "image": "attacker/image:latest",
        "url": "http://demo-target:8080",
    })
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_scope_cannot_escape_target_origin_or_path(client):
    project = (await client.post("/api/v1/projects", json={"name": "scope"})).json()
    target = (await client.post("/api/v1/targets", json={
        "project_id": project["id"],
        "name": "demo",
        "url": "https://example.test/app",
    })).json()
    for allowed_url in (
        "https://other.example/app",
        "https://example.test/application",
        "https://example.test/app/../secret",
    ):
        response = await client.post("/api/v1/authorization-scopes", json={
            "project_id": project["id"],
            "target_id": target["id"],
            "allowed_url": allowed_url,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        assert response.status_code == 400

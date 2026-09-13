from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

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
        "owned_demo": True,
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
        "owned_demo": True,
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
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    report = (
        await client.get(f"/api/v1/assessments/{result.json()['id']}/results")
    ).json()
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
        "owned_demo": True,
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
            headers={"Authorization": "Bearer test-key"},
            json={"name": "protected"},
        )
        assert response.status_code == 200
    finally:
        settings.api_key = original_key

import asyncio
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
    target = (
        await client.post(
            "/api/v1/targets",
            json={
                "project_id": project["id"],
                "name": "demo",
                "url": "http://demo-target:8080",
            },
        )
    ).json()
    response = await client.post(
        "/api/v1/assessments",
        json={
            "project_id": project["id"],
            "target_id": target["id"],
            "scope_id": "missing",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_passive_assessment_returns_json_and_cleanup(client):
    project = (await client.post("/api/v1/projects", json={"name": "demo2"})).json()
    target = (
        await client.post(
            "/api/v1/targets",
            json={
                "project_id": project["id"],
                "name": "demo",
                "url": "http://demo-target:8080",
            },
        )
    ).json()
    scope = (
        await client.post(
            "/api/v1/authorization-scopes",
            json={
                "project_id": project["id"],
                "target_id": target["id"],
                "allowed_url": "http://demo-target:8080",
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(hours=1)
                ).isoformat(),
            },
        )
    ).json()
    result = await client.post(
        "/api/v1/assessments",
        json={
            "project_id": project["id"],
            "target_id": target["id"],
            "scope_id": scope["id"],
        },
    )
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
    assessment = (await client.get(result.headers["location"])).json()
    assert assessment["status"] == "completed"
    assert assessment["result"] == report["result"]
    audit = (await client.get(f"/api/v1/projects/{project['id']}/audit-events")).json()
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
    target = (
        await client.post(
            "/api/v1/targets",
            json={
                "project_id": project["id"],
                "name": "demo",
                "url": "http://demo-target:8080",
            },
        )
    ).json()
    scope = await client.post(
        "/api/v1/authorization-scopes",
        json={
            "project_id": project["id"],
            "target_id": target["id"],
            "allowed_url": "http://demo-target:8080",
            "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        },
    )
    assert scope.status_code == 400


@pytest.mark.asyncio
async def test_target_image_must_be_allowlisted(client):
    project = (await client.post("/api/v1/projects", json={"name": "images"})).json()
    response = await client.post(
        "/api/v1/targets",
        json={
            "project_id": project["id"],
            "name": "untrusted",
            "image": "attacker/image:latest",
            "url": "http://demo-target:8080",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_image", [False, True])
async def test_target_stores_default_or_explicit_allowed_image(
    client, monkeypatch, explicit_image
):
    from app.db import SessionLocal
    from app.models import Target

    alternative = "seireth/alternative:local"
    monkeypatch.setattr(
        settings,
        "docker_allowed_target_images",
        [settings.docker_target_image, alternative],
    )
    project = (
        await client.post("/api/v1/projects", json={"name": "allowed-images"})
    ).json()
    payload = {"project_id": project["id"], "name": "allowed"}
    if explicit_image:
        payload["image"] = alternative
    response = await client.post("/api/v1/targets", json=payload)
    assert response.status_code == 200
    with SessionLocal() as db:
        target = db.get(Target, response.json()["id"])
        assert target.image == (
            alternative if explicit_image else settings.docker_target_image
        )


@pytest.mark.asyncio
async def test_default_image_must_also_be_allowlisted(client, monkeypatch):
    monkeypatch.setattr(settings, "docker_allowed_target_images", [])
    project = (
        await client.post("/api/v1/projects", json={"name": "denied-default"})
    ).json()
    response = await client.post(
        "/api/v1/targets", json={"project_id": project["id"], "name": "default"}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_queued_and_cancelled_before_execution_have_no_result(
    client, monkeypatch
):
    from app.main import dispatcher

    submitted = []
    monkeypatch.setattr(dispatcher, "submit", submitted.append)
    project = (await client.post("/api/v1/projects", json={"name": "queued"})).json()
    target = (
        await client.post(
            "/api/v1/targets", json={"project_id": project["id"], "name": "demo"}
        )
    ).json()
    scope = (
        await client.post(
            "/api/v1/authorization-scopes",
            json={
                "project_id": project["id"],
                "target_id": target["id"],
                "allowed_url": "http://demo-target:8080",
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=5)
                ).isoformat(),
            },
        )
    ).json()
    response = await client.post(
        "/api/v1/assessments",
        json={
            "project_id": project["id"],
            "target_id": target["id"],
            "scope_id": scope["id"],
        },
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


@pytest.mark.asyncio
async def test_scope_cannot_escape_target_origin_or_path(client):
    project = (await client.post("/api/v1/projects", json={"name": "scope"})).json()
    target = (
        await client.post(
            "/api/v1/targets",
            json={
                "project_id": project["id"],
                "name": "demo",
                "url": "https://example.test/app",
            },
        )
    ).json()
    for allowed_url in (
        "https://other.example/app",
        "https://example.test/application",
        "https://example.test/app/../secret",
    ):
        response = await client.post(
            "/api/v1/authorization-scopes",
            json={
                "project_id": project["id"],
                "target_id": target["id"],
                "allowed_url": allowed_url,
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(hours=1)
                ).isoformat(),
            },
        )
        assert response.status_code == 400

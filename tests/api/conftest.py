"""HTTP fixtures; read_client deliberately omits dispatcher startup."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.router import router


@pytest.fixture
def client(database):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def read_client(database):
    application = FastAPI()
    application.include_router(router)
    with TestClient(application) as client:
        yield client


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


@pytest.fixture
def dispatch_calls(client, monkeypatch):
    from app.assessments.worker import dispatcher

    calls = {"submit": [], "cancel": []}
    for method, recorded in calls.items():
        monkeypatch.setattr(dispatcher, method, recorded.append)
    return calls

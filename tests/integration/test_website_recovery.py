"""Actual API process death closes HTTP and preserves partial data without replay."""

import pytest
from sqlalchemy import select

from app.persistence import models
from tests.api.helpers import register


@pytest.mark.parametrize("api_process", ["http"], indirect=True)
def test_website_completion_and_report_survive_restart_without_docker(
    api_process, website, wait_until
):
    api = api_process
    client = api.client
    project = client.post("/api/v1/projects", json={"name": "native website"}).json()
    target = register(client, project["id"], website)
    submitted = client.post(
        "/api/v1/assessments",
        json={
            "project_id": project["id"],
            "target_id": target,
            "url": website.url,
            "plugins": ["http-security-headers"],
        },
    )
    assert submitted.status_code == 202, submitted.text
    path = submitted.headers["location"]
    wait_until(
        lambda: client.get(path).json()["status"],
        lambda status: status == "completed",
        description="native website completion",
    )
    report = client.get(path + "/report").json()
    assert report["schema_version"] == 1
    assert report["assessment"]["result"]["sandbox_backend"] == "http"
    assert report["assessment"]["result"]["cleanup_verified"]
    assert report["findings"] and website.handler.requests
    api.process.terminate()
    api.process.wait(timeout=10)
    api.start()
    refreshed = client.get(path + "/report").json()
    report.pop("generated_at")
    refreshed.pop("generated_at")
    assert refreshed == report


@pytest.mark.parametrize("api_process", ["http"], indirect=True)
def test_native_website_restart_preserves_partial_results_without_retry(
    api_process, website, wait_until, database
):
    api = api_process
    client = api.client
    project = client.post("/api/v1/projects", json={"name": "owned website"}).json()
    target = register(client, project["id"], website)
    response = client.post(
        "/api/v1/assessments",
        json={
            "project_id": project["id"],
            "target_id": target,
            "routes": [
                {
                    "key": "root",
                    "url": website.url,
                    "plugins": ["http-security-headers"],
                },
                {
                    "key": "slow",
                    "url": website.url + "slow",
                    "plugins": ["http-security-headers"],
                },
            ],
        },
    )
    assert response.status_code == 202, response.text
    identifier = response.json()["id"]
    wait_until(
        lambda: any(path == "/slow" for path, *_ in website.handler.requests),
        description="native second route started",
        timeout=10,
    )
    api.process.kill()
    api.process.wait(timeout=10)
    api.start()
    result = client.get(f"/api/v1/assessments/{identifier}/results").json()
    assert result["status"] == "failed", result
    assert result["result"]["execution_outcome"] == "interrupted"
    assert result["result"]["cleanup_verified"]
    assert result["result"]["partial"]
    assert len(result["findings"]) == 2
    assert len(website.handler.requests) == 2
    report = client.get(f"/api/v1/assessments/{identifier}/report")
    assert report.status_code == 200, report.text
    assert len(report.json()["evidence"]) == 2
    with database.SessionLocal() as db:
        attempts = list(
            db.scalars(
                select(models.Attempt).where(models.Attempt.assessment_id == identifier)
            )
        )
        assert len(attempts) == 1
    first = report.json()
    api.process.kill()
    api.process.wait(timeout=10)
    api.start()
    second = client.get(f"/api/v1/assessments/{identifier}/report").json()
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second
    assert len(website.handler.requests) == 2

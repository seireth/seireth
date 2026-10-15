"""End-to-end native website admission, execution, evidence, and release decisions."""

import json

from sqlalchemy import select

from app.assessments import images
from app.assessments.worker import dispatcher
from app.persistence import models
from tests.api.helpers import finish, register, submit
from tests.website import configure


def test_route_storage_failure_still_acknowledges_http_cleanup(
    client, project, website, tmp_path, monkeypatch, wait_until
):
    configure(monkeypatch, tmp_path, website)
    target = register(client, project, website)

    def writer(*args):
        def persist(data, results):
            raise RuntimeError("private storage diagnostic")

        return persist

    monkeypatch.setattr(dispatcher, "_route_writer", writer)
    identifier = submit(client, project, target, website.url)
    result, report = finish(client, identifier, wait_until)
    assert result["status"] == "failed"
    assert result["result"]["cleanup_verified"] and not result["cleanup_pending"]
    assert result["result"]["verdict"]["status"] == "blocked"
    assert not result["result"]["coverage"]["complete"]
    assert report["findings"] == report["evidence"] == []
    assert "private storage diagnostic" not in json.dumps(report)
    assert len(website.handler.requests) == 1


def test_real_website_before_after_and_compatible_baseline(
    client, project, website, tmp_path, monkeypatch, wait_until, database
):
    configure(monkeypatch, tmp_path, website)
    monkeypatch.setattr(
        images,
        "_command",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("website must not use Docker")
        ),
    )
    target = register(client, project, website)
    before = submit(client, project, target, website.url)
    result, report = finish(client, before, wait_until)
    assert result["status"] == "completed"
    assert report["schema_version"] == 1
    assert len(report["findings"]) == 5
    assert len(report["evidence"]) == 5
    assert result["result"]["coverage"]["complete"]
    assert result["result"]["verdict"]["status"] == "blocked"
    assert all(finding["route_result_id"] for finding in report["findings"])
    website.handler.corrected = True
    after = submit(client, project, target, website.url, baseline=before)
    result, report = finish(client, after, wait_until)
    assert result["result"]["verdict"]["status"] == "pass"
    assert result["findings"] == []
    assert len(result["result"]["comparison"]["resolved"]) == 5
    assert len(website.handler.requests) == 2
    with database.SessionLocal() as db:
        attempt = db.scalar(
            select(models.Attempt).where(models.Attempt.assessment_id == after)
        )
        assert (
            attempt.backend == "http"
            and attempt.http_closed
            and attempt.cleanup_verified
        )


def test_authentication_coverage_and_redaction(
    client, project, website, tmp_path, monkeypatch, wait_until
):
    configure(monkeypatch, tmp_path, website)
    target = register(client, project, website)
    unauthenticated = submit(client, project, target, website.url + "private")
    result, report = finish(client, unauthenticated, wait_until)
    assert result["result"]["verdict"]["status"] == "blocked"
    assert not result["result"]["coverage"]["complete"]
    authenticated = submit(
        client,
        project,
        target,
        website.url + "private",
        request_profile="authenticated",
    )
    result, report = finish(client, authenticated, wait_until)
    assert result["result"]["coverage"]["complete"]
    assert website.handler.requests[-1][1] == "Bearer fixture-secret"
    assert "fixture-secret" not in json.dumps(report)


def test_partial_route_failure_publishes_only_complete_routes_after_cleanup(
    client, project, website, tmp_path, monkeypatch, wait_until
):
    configure(monkeypatch, tmp_path, website)
    target = register(client, project, website)
    response = client.post(
        "/api/v1/assessments",
        json={
            "project_id": project,
            "target_id": target,
            "routes": [
                {
                    "key": "good",
                    "url": website.url,
                    "plugins": ["http-security-headers"],
                },
                {
                    "key": "slow",
                    "url": website.url + "slow",
                    "plugins": ["http-security-headers"],
                    "request_seconds": 0.01,
                },
            ],
        },
    )
    assert response.status_code == 202
    result, report = finish(client, response.json()["id"], wait_until)
    assert result["status"] == "failed" and not result["cleanup_pending"]
    assert result["result"]["partial"]
    assert len(report["findings"]) == 2
    assert len(report["evidence"]) == 2
    assert result["result"]["routes"][1]["status"] == "failed"
    assert result["result"]["verdict"]["status"] == "blocked"


def test_baseline_with_missing_evidence_cannot_claim_findings_resolved(
    client, project, website, tmp_path, monkeypatch, wait_until, database
):
    configure(monkeypatch, tmp_path, website)
    target = register(client, project, website)
    baseline = submit(client, project, target, website.url)
    _, report = finish(client, baseline, wait_until)
    with database.SessionLocal() as db:
        db.delete(db.get(models.Evidence, report["evidence"][0]["id"]))
        db.commit()
    website.handler.corrected = True
    current = submit(client, project, target, website.url, baseline=baseline)
    result, _ = finish(client, current, wait_until)
    assert result["result"]["verdict"]["status"] == "pass"
    assert result["result"]["comparison"] == {
        "status": "unavailable",
        "reason": "stable finding identities are unavailable",
    }


def test_protected_html_error_page_has_required_coverage(
    client, project, website, monkeypatch, tmp_path, wait_until
):
    configure(monkeypatch, tmp_path, website)
    website.handler.corrected = True
    target = register(client, project, website)
    identifier = submit(
        client,
        project,
        target,
        website.url + "missing",
        expected={"statuses": [404], "media_types": ["text/html"]},
    )
    _, report = finish(client, identifier, wait_until)
    result = report["assessment"]["result"]
    assert result["verdict"]["status"] == "pass"
    assert result["coverage"]["complete"] and result["cleanup_verified"]
    assert report["findings"] == report["evidence"] == []
    assert website.handler.requests[0][0] == "/missing"

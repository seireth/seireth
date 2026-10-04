from datetime import datetime, timedelta, timezone

import pytest

from tests.api.helpers import snapshot


def test_expired_scope_is_rejected(client, scope_payload):
    scope_payload["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    response = client.post("/api/v1/authorization-scopes", json=scope_payload)
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

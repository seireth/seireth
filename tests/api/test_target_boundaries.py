import pytest

from tests.api.helpers import snapshot, submission


@pytest.mark.parametrize(
    "url", ["https://example.test/app", "https://example.test:443/app/child?x=1"]
)
@pytest.mark.parametrize("target", ["https://example.test/app"], indirect=True)
def test_response_url_accepts_registered_path_and_children(
    client, assessment_payload, dispatch_calls, url
):
    response = client.post(
        "/api/v1/assessments", json={**assessment_payload, "url": url}
    )
    assert response.status_code == 202
    assert response.json()["url"] == url.replace(":443", "")


@pytest.mark.parametrize(
    "url,status",
    [
        ("https://other.test/app", 403),
        ("http://example.test/app", 403),
        ("https://example.test:444/app", 403),
        ("https://example.test:0/app", 403),
        ("https://example.test/application", 403),
        ("https://example.test/outside", 403),
        ("https://example.test/app/../secret", 422),
        ("https://example.test/app/%2e%2e/secret", 422),
        ("https://example.test/app/%252e%252e/secret", 422),
        ("https://example.test/app\\secret", 422),
        ("https://user:pass@example.test/app", 422),
        ("https://example.test/app#fragment", 422),
    ],
)
@pytest.mark.parametrize("target", ["https://example.test/app"], indirect=True)
def test_response_url_rejects_outside_or_unsafe_boundaries(
    client, database, assessment_payload, dispatch_calls, url, status
):
    before = snapshot(database)
    response = client.post(
        "/api/v1/assessments", json={**assessment_payload, "url": url}
    )
    assert response.status_code == status
    assert snapshot(database) == before
    assert dispatch_calls["submit"] == []


def test_url_is_required_and_old_scope_contract_is_removed(
    read_client, assessment_graph
):
    graph = assessment_graph()
    payload = submission(graph)
    del payload["url"]
    payload["scope_id"] = "old-scope"
    assert read_client.post("/api/v1/assessments", json=payload).status_code == 422
    for path in [
        "/authorization-scopes",
        "/authorization-scopes/missing",
        f"/projects/{graph.project.id}/authorization-scopes",
    ]:
        assert read_client.get("/api/v1" + path).status_code == 404
        assert read_client.post("/api/v1" + path, json={}).status_code == 404

import pytest

from tests.api.helpers import snapshot, submission


@pytest.mark.parametrize(
    "operation",
    ["target", "assessment", "read", "results", "evidence", "cancel", "audit"],
)
def test_foreign_project_access_is_denied_without_side_effects(
    client, database, assessment_graph, dispatch_calls, operation
):
    graph = assessment_graph(owner="other-actor", status="completed")
    aid, pid = graph.assessment.id, graph.project.id
    requests = {
        "target": (
            "post",
            "/api/v1/targets",
            {
                "project_id": pid,
                "name": "foreign",
                "image": graph.target.image,
                "url": graph.target.url,
            },
        ),
        "assessment": ("post", "/api/v1/assessments", submission(graph)),
        "read": ("get", f"/api/v1/assessments/{aid}", None),
        "results": ("get", f"/api/v1/assessments/{aid}/results", None),
        "evidence": ("get", f"/api/v1/assessments/{aid}/evidence", None),
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


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/v1/assessments/missing"),
        ("get", "/api/v1/assessments/missing/results"),
        ("post", "/api/v1/assessments/missing/cancel"),
        ("get", "/api/v1/projects/missing/audit-events"),
        ("post", "/api/v1/targets"),
        ("post", "/api/v1/assessments"),
    ],
)
def test_missing_resources_return_404_without_side_effects(
    client, database, dispatch_calls, method, path
):
    payload = {
        "project_id": "missing",
        "name": "missing",
        "image": "demo:local",
        "url": "http://demo-app:8080/",
    }
    if path == "/api/v1/assessments":
        payload = {
            "project_id": "missing",
            "target_id": "missing",
            "url": "http://demo-app:8080/",
            "plugins": ["security-headers"],
        }
    before = snapshot(database)
    response = client.request(method, path, json=payload if method == "post" else None)
    assert response.status_code == 404
    assert snapshot(database) == before
    assert dispatch_calls == {"submit": [], "cancel": []}


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "https://other.test",
        "http://testserver:81",
        "http://testserver:0",
        "http://testserver/",
        "http://user@testserver",
        "http://@testserver",
        "http://testserver?query",
        "http://[bad",
        "http://testserver https://other.test",
        "http://testserver\n",
    ],
)
def test_cross_origin_writes_fail_before_side_effects(read_client, database, origin):
    before = snapshot(database)
    assert (
        read_client.post(
            "/api/v1/projects", headers={"Origin": origin}, json={"name": "denied"}
        ).status_code
        == 403
    )
    assert snapshot(database) == before
    assert (
        read_client.post(
            "/api/v1/assessments/missing/cancel", headers={"Origin": origin}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("origin", [None, "http://testserver", "http://testserver:80"])
def test_same_origin_and_cli_writes(read_client, origin):
    headers = {} if origin is None else {"Origin": origin}
    assert (
        read_client.post(
            "/api/v1/projects", headers=headers, json={"name": "authorized"}
        ).status_code
        == 200
    )

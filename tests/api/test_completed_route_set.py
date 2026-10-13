"""A completed route set exports the current report contract."""

from tests.api.helpers import finish, register
from tests.website import configure


def test_completed_html_and_json_route_set_exports_a_passing_report(
    client, project, website, tmp_path, monkeypatch, wait_until
):
    configure(monkeypatch, tmp_path, website)
    website.handler.corrected = True
    target = register(client, project, website)
    response = client.post(
        "/api/v1/assessments",
        json={
            "project_id": project,
            "target_id": target,
            "routes": [
                {
                    "key": "html",
                    "url": website.url,
                    "plugins": ["http-security-headers", "csp-policy"],
                },
                {
                    "key": "json",
                    "url": website.url + "api",
                    "plugins": ["http-security-headers"],
                    "expected": {
                        "statuses": [200],
                        "media_types": ["application/json"],
                    },
                },
            ],
        },
    )
    assert response.status_code == 202, response.text
    result, report = finish(client, response.json()["id"], wait_until)
    assert result["status"] == "completed"
    assert result["result"]["verdict"]["status"] == "pass"
    assert report["schema_version"] == 1
    assert len(report["assessment"]["result"]["routes"]) == 2
    assert "response" not in report["assessment"]["result"]
    assert report["findings"] == report["evidence"] == []

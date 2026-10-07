def test_plugin_catalog_and_explicit_selection(client, assessment_payload, monkeypatch):
    from app.assessments.worker import dispatcher

    catalog = (client.get("/api/v1/plugins")).json()
    assert [item["id"] for item in catalog] == [
        "http-security-headers",
        "cookie-security",
    ]
    assert all(set(item) == {"id", "name", "description"} for item in catalog)
    assert all(item["name"].strip() and item["description"].strip() for item in catalog)
    monkeypatch.setattr(dispatcher, "submit", lambda assessment_id: None)
    response = client.post(
        "/api/v1/assessments",
        json={**assessment_payload, "plugins": ["http-security-headers"]},
    )
    assert response.status_code == 202
    assert response.json()["plugins"] == ["http-security-headers"]
    stored = (client.get(response.headers["location"])).json()
    assert stored["plugins"] == ["http-security-headers"]


def test_legacy_plugin_id_is_rejected_without_records(
    client, assessment_payload, database
):
    from tests.api.helpers import snapshot

    before = snapshot(database)
    response = client.post(
        "/api/v1/assessments",
        json={**assessment_payload, "plugins": ["security-headers"]},
    )
    assert response.status_code == 400
    assert snapshot(database) == before

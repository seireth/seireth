def test_plugin_catalog_and_explicit_selection(client, assessment_payload, monkeypatch):
    from app.worker import dispatcher

    catalog = (client.get("/api/v1/plugins")).json()
    assert [item["id"] for item in catalog] == ["security-headers", "cookie-security"]
    assert all(set(item) == {"id", "name", "description"} for item in catalog)
    assert all(item["name"].strip() and item["description"].strip() for item in catalog)
    monkeypatch.setattr(dispatcher, "submit", lambda assessment_id: None)
    response = client.post(
        "/api/v1/assessments",
        json={**assessment_payload, "plugins": ["security-headers"]},
    )
    assert response.status_code == 202
    assert response.json()["plugins"] == ["security-headers"]
    stored = (client.get(response.headers["location"])).json()
    assert stored["plugins"] == ["security-headers"]

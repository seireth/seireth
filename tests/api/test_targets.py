import pytest

from app.config import settings


def test_target_image_must_be_allowlisted(client, project):
    response = client.post(
        "/api/v1/targets",
        json={
            "project_id": project,
            "name": "untrusted",
            "image": "attacker/image:latest",
            "url": "http://demo-target:8080",
        },
    )
    assert response.status_code == 400


@pytest.mark.parametrize("explicit_image", [False, True])
def test_target_stores_default_or_explicit_allowed_image(
    client, project, monkeypatch, explicit_image
):
    from app.db import SessionLocal
    from app.models import Target

    alternative = "seireth/alternative:local"
    monkeypatch.setattr(
        settings,
        "docker_allowed_target_images",
        [settings.docker_target_image, alternative],
    )
    payload = {"project_id": project, "name": "allowed"}
    if explicit_image:
        payload["image"] = alternative
    response = client.post("/api/v1/targets", json=payload)
    assert response.status_code == 200
    with SessionLocal() as db:
        target = db.get(Target, response.json()["id"])
        assert target.image == (
            alternative if explicit_image else settings.docker_target_image
        )


def test_default_image_must_also_be_allowlisted(client, project, monkeypatch):
    monkeypatch.setattr(settings, "docker_allowed_target_images", [])
    response = client.post(
        "/api/v1/targets", json={"project_id": project, "name": "default"}
    )
    assert response.status_code == 400

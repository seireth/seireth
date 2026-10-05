import pytest

from app.core.config import settings
from tests.api.helpers import snapshot


@pytest.mark.parametrize("backend", ["inmemory", "docker"])
def test_runtime_exposes_only_operator_configuration(
    read_client, database, monkeypatch, backend
):
    monkeypatch.setattr(settings, "sandbox_backend", backend)
    monkeypatch.setattr(settings, "docker_target_image", "custom-target:v2")
    monkeypatch.setattr(
        settings,
        "docker_allowed_target_images",
        ["custom-target:v2", "other-target:v1"],
    )
    before = snapshot(database)
    response = read_client.get("/api/v1/runtime")
    assert response.status_code == 200
    assert response.json() == {
        "sandbox_backend": backend,
        "default_target_image": "custom-target:v2",
        "allowed_target_images": ["custom-target:v2", "other-target:v1"],
    }
    assert snapshot(database) == before

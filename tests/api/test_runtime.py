import pytest

from app.core.config import settings
from tests.api.helpers import snapshot


@pytest.mark.parametrize("backend", ["inmemory", "docker"])
def test_runtime_exposes_only_operator_configuration(
    read_client, database, monkeypatch, backend
):
    monkeypatch.setattr(settings, "sandbox_backend", backend)
    before = snapshot(database)
    response = read_client.get("/api/v1/runtime")
    assert response.status_code == 200
    assert response.json() == {
        "sandbox_backend": backend,
    }
    assert snapshot(database) == before

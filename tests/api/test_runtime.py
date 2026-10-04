from tests.api.helpers import snapshot


def test_runtime_exposes_only_operator_configuration(read_client, database):
    before = snapshot(database)
    assert set(read_client.get("/api/v1/runtime").json()) == {
        "sandbox_backend",
        "default_target_image",
        "allowed_target_images",
    }
    assert snapshot(database) == before

"""Only useful runtime profile metadata is exposed."""

from tests.api.helpers import snapshot


def test_runtime_profiles_are_read_only(read_client, database):
    before = snapshot(database)
    assert read_client.get("/api/v1/runtime/profiles").json() == {
        "requests": {},
        "launches": {},
        "networks": {},
        "trusts": [],
    }
    assert snapshot(database) == before

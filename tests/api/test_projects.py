from datetime import timedelta

import pytest

from app.persistence import models
from tests.api.helpers import snapshot


def test_saved_work_reads_are_authorized_scoped_ordered_and_read_only(
    read_client, database, assessment_graph
):
    first = assessment_graph(status="completed")
    second = assessment_graph(status="failed")
    denied = assessment_graph(owner="other-actor", status="completed")
    with database.SessionLocal() as db:
        scope = db.get(models.AuthorizationScope, first.scope.id)
        scope.expires_at = models.now() - timedelta(hours=1)
        for identity in ["a", "b"]:
            db.add(
                models.Target(
                    id=identity,
                    project_id=first.project.id,
                    name=identity,
                    image=first.target.image,
                    url=first.target.url,
                )
            )
        db.commit()
    before = snapshot(database)
    projects = read_client.get("/api/v1/projects?limit=1").json()
    assert projects["has_more"]
    assert projects["items"][0]["id"] == second.project.id
    assert (
        read_client.get("/api/v1/projects?offset=1&limit=1").json()["items"][0]["id"]
        == first.project.id
    )
    targets = read_client.get(
        f"/api/v1/projects/{first.project.id}/targets?limit=1"
    ).json()
    expected = sorted([first.target.id, "a", "b"])
    assert targets["items"][0]["id"] == expected[0]
    assert targets["has_more"]
    assert (
        read_client.get(
            f"/api/v1/projects/{first.project.id}/targets?offset=1&limit=1"
        ).json()["items"][0]["id"]
        == expected[1]
    )
    scopes = read_client.get(
        f"/api/v1/projects/{first.project.id}/authorization-scopes?target_id={first.target.id}"
    ).json()
    assert [s["id"] for s in scopes["items"]] == [first.scope.id]
    assert scopes["items"][0]["expires_at"] < models.now().isoformat()
    assert (
        read_client.get(
            f"/api/v1/projects/{first.project.id}/authorization-scopes?target_id={second.target.id}"
        ).status_code
        == 404
    )
    runs = read_client.get(f"/api/v1/projects/{first.project.id}/assessments").json()[
        "items"
    ]
    assert len(runs) == 1 and runs[0]["target_id"] == first.target.id
    assert runs[0]["scope_id"] == first.scope.id and runs[0]["created_at"]
    for resource, identity in [
        ("projects", first.project.id),
        ("targets", first.target.id),
        ("authorization-scopes", first.scope.id),
    ]:
        assert read_client.get(f"/api/v1/{resource}/{identity}").status_code == 200
        assert read_client.get(f"/api/v1/{resource}/missing").status_code == 404
    for resource, identity in [
        ("projects", denied.project.id),
        ("targets", denied.target.id),
        ("authorization-scopes", denied.scope.id),
    ]:
        assert read_client.get(f"/api/v1/{resource}/{identity}").status_code == 403
    for resource in ["targets", "authorization-scopes", "assessments"]:
        assert (
            read_client.get(
                f"/api/v1/projects/{denied.project.id}/{resource}"
            ).status_code
            == 403
        )
        assert (
            read_client.get(f"/api/v1/projects/missing/{resource}").status_code == 404
        )
    assert snapshot(database) == before


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=wrong"])
def test_invalid_list_bounds(read_client, query):
    assert read_client.get(f"/api/v1/projects?{query}").status_code == 422

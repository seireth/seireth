import pytest

from app.assessments import images
from tests.api.helpers import snapshot, submission


@pytest.mark.parametrize("field", ["image", "url"])
def test_target_requires_image_and_url(client, project, field):
    payload = {
        "project_id": project,
        "name": "target",
        "image": "other:local",
        "url": "http://other:8080/",
    }
    del payload[field]
    response = client.post("/api/v1/targets", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]


@pytest.mark.parametrize(
    "error,status",
    [
        (images.ImageUnavailable("Image missing locally"), 400),
        (images.DockerUnavailable("Docker unavailable"), 503),
    ],
)
@pytest.mark.parametrize("operation", ["target", "assessment"])
def test_unavailable_image_or_daemon_rejects_without_side_effects(
    read_client, database, assessment_graph, monkeypatch, error, status, operation
):
    graph = assessment_graph()

    def unavailable(image):
        assert image == graph.target.image
        raise error

    monkeypatch.setattr(
        images,
        "inspect_image" if operation == "assessment" else "require_local_image",
        unavailable,
    )
    payload = (
        submission(graph)
        if operation == "assessment"
        else {
            "project_id": graph.project.id,
            "name": "target",
            "image": graph.target.image,
            "url": graph.target.url,
        }
    )
    before = snapshot(database)
    response = read_client.post(
        f"/api/v1/{'assessments' if operation == 'assessment' else 'targets'}",
        json=payload,
    )
    assert response.status_code == status
    assert response.json()["detail"] == str(error)
    assert snapshot(database) == before


def test_image_discovery_and_daemon_failure(read_client, monkeypatch):
    available = [{"image": "arbitrary:v1", "id": "sha256:" + "a" * 64}]
    monkeypatch.setattr(images, "local_images", lambda: available)
    assert read_client.get("/api/v1/target-images").json() == {"items": available}

    def failed():
        raise images.DockerUnavailable("Docker image discovery unavailable")

    monkeypatch.setattr(images, "local_images", failed)
    assert read_client.get("/api/v1/target-images").status_code == 503

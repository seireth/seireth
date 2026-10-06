"""Local image discovery and error classification without a Docker installation."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from app.assessments import images
from app.core.config import settings


@pytest.fixture
def docker_backend(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_backend", "docker")


@pytest.mark.parametrize("backend", ["inmemory", "docker"])
def test_image_availability_uses_explicit_reference_and_no_pulls(monkeypatch, backend):
    monkeypatch.setattr(settings, "sandbox_backend", backend)
    run = Mock(
        return_value=subprocess.CompletedProcess([], 0, "sha256:" + "a" * 64, "")
    )
    monkeypatch.setattr(images.subprocess, "run", run)
    images.require_local_image("unlisted/application:v2")
    if backend == "inmemory":
        run.assert_not_called()
        assert images.local_images() == []
    else:
        assert run.call_args.args[0] == [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            "unlisted/application:v2",
        ]


@pytest.mark.usefixtures("docker_backend")
@pytest.mark.parametrize(
    "daemon_status,error", [(0, images.ImageUnavailable), (1, images.DockerUnavailable)]
)
def test_missing_image_is_distinct_from_daemon_failure(
    monkeypatch, daemon_status, error
):
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 1, "", "failure"),
            subprocess.CompletedProcess([], daemon_status, "", ""),
        ]
    )
    monkeypatch.setattr(images.subprocess, "run", run)
    with pytest.raises(error):
        images.require_local_image("missing:local")
    assert run.call_args.args[0][:2] == ["docker", "info"]
    assert all("pull" not in call.args[0] for call in run.call_args_list)


@pytest.mark.usefixtures("docker_backend")
@pytest.mark.parametrize(
    "error", [FileNotFoundError(), subprocess.TimeoutExpired("docker", 15)]
)
def test_cli_unavailable_or_timeout_is_service_failure(monkeypatch, error):
    monkeypatch.setattr(images.subprocess, "run", Mock(side_effect=error))
    with pytest.raises(images.DockerUnavailable):
        images.require_local_image("app:local")
    with pytest.raises(images.DockerUnavailable):
        images.local_images()


@pytest.mark.usefixtures("docker_backend")
def test_discovery_returns_sorted_unique_tagged_images(monkeypatch):
    identity = "sha256:" + "a" * 64
    rows = [
        {"Repository": repository, "Tag": tag, "ID": identity}
        for repository, tag in [
            ("z/app", "v2"),
            ("a/app", "local"),
            ("a/app", "local"),
            ("<none>", "<none>"),
            ("app", "<none>"),
        ]
    ]
    run = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, "\n".join(map(json.dumps, rows)), ""
        )
    )
    monkeypatch.setattr(images.subprocess, "run", run)
    assert images.local_images() == [
        {"image": "a/app:local", "id": identity},
        {"image": "z/app:v2", "id": identity},
    ]
    assert "--no-trunc" in run.call_args.args[0]


@pytest.mark.usefixtures("docker_backend")
@pytest.mark.parametrize("status,output", [(1, ""), (0, "not-json"), (0, "{}")])
def test_failed_or_malformed_discovery_returns_service_failure(
    monkeypatch, status, output
):
    monkeypatch.setattr(
        images.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], status, output, "")),
    )
    with pytest.raises(images.DockerUnavailable):
        images.local_images()

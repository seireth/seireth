"""Local image availability and error classification without Docker."""

import subprocess
from unittest.mock import Mock

import pytest

from app.assessments import images


def test_image_availability_uses_explicit_reference_and_no_pulls(monkeypatch):
    run = Mock(
        return_value=subprocess.CompletedProcess([], 0, "sha256:" + "a" * 64, "")
    )
    monkeypatch.setattr(images.subprocess, "run", run)
    images.require_local_image("unlisted/application:v2")
    assert run.call_args.args[0] == [
        "docker",
        "image",
        "inspect",
        "--format",
        "{{.Id}}",
        "unlisted/application:v2",
    ]


@pytest.mark.parametrize("inspect", [images.require_local_image, images.inspect_image])
@pytest.mark.parametrize(
    "daemon_status,error", [(0, images.ImageUnavailable), (1, images.DockerUnavailable)]
)
def test_missing_image_is_distinct_from_daemon_failure(
    monkeypatch, daemon_status, error, inspect
):
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess([], 1, "", "failure"),
            subprocess.CompletedProcess([], daemon_status, "", ""),
        ]
    )
    monkeypatch.setattr(images.subprocess, "run", run)
    with pytest.raises(error):
        inspect("missing:local")
    assert run.call_count == 2
    assert run.call_args.args[0][:2] == ["docker", "info"]
    assert all("pull" not in call.args[0] for call in run.call_args_list)


@pytest.mark.parametrize(
    "error", [FileNotFoundError(), subprocess.TimeoutExpired("docker", 15)]
)
def test_cli_unavailable_or_timeout_is_service_failure(monkeypatch, error):
    monkeypatch.setattr(images.subprocess, "run", Mock(side_effect=error))
    with pytest.raises(images.DockerUnavailable):
        images.require_local_image("app:local")
    with pytest.raises(images.DockerUnavailable):
        images.local_images()

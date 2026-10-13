"""Operator launch validation prevents resource collisions and unsafe mounts."""

import pytest
from pydantic import ValidationError

from app.assessments.profiles import ContainerSpec, LaunchProfile, VolumeSpec


def test_runtime_secret_can_be_multiline_environment_but_not_a_header(monkeypatch):
    from app.assessments.policy import PolicyError
    from app.assessments.profiles import OperatorConfig, resolve_secret

    config = OperatorConfig(secrets={"key": {"env": "CONTROLLED_KEY"}})
    monkeypatch.setenv("CONTROLLED_KEY", "controlled\nmultiline")
    assert resolve_secret("key", config) == "controlled\nmultiline"
    with pytest.raises(PolicyError):
        resolve_secret("key", config, header=True)


@pytest.mark.parametrize(
    "name", ["network", "runner", "target", "initializer", "volume-database"]
)
def test_service_names_cannot_collide_with_lifecycle_resources(name):
    with pytest.raises(ValidationError):
        LaunchProfile(services={name: {"image": "fixture:local"}})


@pytest.mark.parametrize(
    "path",
    ["/", "/../etc", "relative", "/foo,source=/host", "/proc/foo", "/dev", "/sys"],
)
def test_mounts_cannot_change_docker_mount_options_or_kernel_paths(path):
    with pytest.raises(ValidationError):
        VolumeSpec(name="data", path=path)


def test_launch_requires_acyclic_declared_dependencies_and_unique_volumes():
    with pytest.raises(ValidationError):
        LaunchProfile(
            services={"db": {"image": "db:local", "depends_on": ["target"]}},
            target={"depends_on": ["db"]},
        )
    with pytest.raises(ValidationError):
        LaunchProfile(target={"depends_on": ["unknown"]})
    with pytest.raises(ValidationError):
        LaunchProfile(
            target={
                "volumes": [
                    {"name": "data", "path": "/data"},
                    {"name": "data", "path": "/other"},
                ]
            }
        )
    with pytest.raises(ValidationError):
        ContainerSpec(
            environment={"SECRET": "public"}, secret_environment={"SECRET": "reference"}
        )

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_test_bootstrap_isolates_operator_settings_and_preserves_test_switches(
    tmp_path,
):
    (tmp_path / ".env").write_text(
        "SEIRETH_DOCKER_PIDS_LIMIT=0\nSEIRETH_DOCKER_RUNNER_IMAGE=operator:custom\n"
    )
    admin_url = "postgresql+psycopg://unused:unused@127.0.0.1/test-admin"
    env = {
        **os.environ,
        "SEIRETH_DOCKER_CPUS": "0",
        "SEIRETH_TEST_ADMIN_URL": admin_url,
        "SEIRETH_DOCKER_TESTS": "1",
    }
    root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(root)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, os, runpy, sys; runpy.run_path(sys.argv[1]); "
            "from app.core.config import Settings; "
            "print(json.dumps([Settings().model_dump(), "
            "os.environ['SEIRETH_TEST_ADMIN_URL'], os.environ['SEIRETH_DOCKER_TESTS']]))",
            str(root / "tests" / "conftest.py"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    settings, actual_admin_url, docker_tests = json.loads(result.stdout)
    assert settings == Settings(_env_file=None).model_dump()
    assert actual_admin_url == admin_url
    assert docker_tests == "1"


@pytest.mark.parametrize(
    "host,expected",
    [
        ("0.0.0.0", "127.0.0.1"),
        ("::", "[::1]"),
        ("[::]", "[::1]"),
        ("::1", "[::1]"),
        ("127.0.0.2", "127.0.0.2"),
    ],
)
def test_verification_uses_connectable_address(host, expected):
    assert (
        Settings(_env_file=None, api_host=host, api_port=9000).api_base_url
        == f"http://{expected}:9000"
    )


@pytest.mark.parametrize("port", [-1, 0, 65536, 70000])
def test_invalid_api_port_is_rejected(port):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, api_port=port)
    assert error.value.errors()[0]["loc"] == ("api_port",)


def test_runner_image_uses_environment_override(monkeypatch):
    monkeypatch.setenv("SEIRETH_DOCKER_RUNNER_IMAGE", "python:custom")
    assert Settings(_env_file=None).docker_runner_image == "python:custom"


@pytest.mark.parametrize(
    "field", ["docker_target_image", "docker_allowed_target_images"]
)
@pytest.mark.parametrize("length", [300, 301])
def test_target_image_settings_respect_storage_limit(monkeypatch, field, length):
    image = "a" * length
    value = json.dumps(["demo:local", image]) if field.endswith("images") else image
    monkeypatch.setenv(f"SEIRETH_{field.upper()}", value)
    if length == 301:
        with pytest.raises(ValidationError) as error:
            Settings(_env_file=None)
        assert error.value.errors()[0]["loc"][0] == field
    else:
        settings = Settings(_env_file=None)
        assert getattr(settings, field) == (
            ["demo:local", image] if field.endswith("images") else image
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("database_url", "sqlite:///test.db"),
        ("database_url", "postgresql://user:pass@localhost/test"),
        ("sandbox_backend", "unknown"),
    ],
)
def test_unsupported_runtime_configuration_is_rejected(field, value):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **{field: value})
    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize(
    "field", ["assessment_timeout_seconds", "docker_timeout_seconds", "docker_cpus"]
)
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_execution_limits_must_be_finite_and_positive(field, value):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, **{field: value})
    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("value", [0, -1])
def test_docker_pids_limit_must_be_positive(value):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, docker_pids_limit=value)
    assert error.value.errors()[0]["loc"] == ("docker_pids_limit",)


@pytest.mark.parametrize(
    "field,value", [("docker_cpus", 0.25), ("docker_pids_limit", 1)]
)
def test_valid_docker_resource_limits_are_accepted(field, value):
    assert getattr(Settings(_env_file=None, **{field: value}), field) == value

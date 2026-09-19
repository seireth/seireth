import pytest
from pydantic import ValidationError

from app.config import Settings


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
        Settings(api_host=host, api_port=9000).api_base_url == f"http://{expected}:9000"
    )


@pytest.mark.parametrize("port", [-1, 0, 65536, 70000])
def test_invalid_api_port_is_rejected(port):
    with pytest.raises(ValidationError):
        Settings(api_port=port)


def test_runner_image_uses_environment_override(monkeypatch):
    monkeypatch.setenv("SEIRETH_DOCKER_RUNNER_IMAGE", "python:custom")
    assert Settings().docker_runner_image == "python:custom"

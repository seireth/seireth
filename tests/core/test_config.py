import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize(
    "field,value",
    [
        ("database_url", "sqlite:///test.db"),
        ("database_url", "postgresql://user:pass@localhost/test"),
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

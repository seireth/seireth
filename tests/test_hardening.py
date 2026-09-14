import pytest

from app.config import settings
from app.main import bounded_url
from app.worker import AssessmentWorker


def test_scope_requires_a_path_boundary():
    assert bounded_url("https://example.test/app/login", "https://example.test/app")
    assert not bounded_url("https://example.test/application", "https://example.test/app")
    assert not bounded_url("https://user:pass@example.test/app", "https://example.test/app")
    assert not bounded_url("https://example.test/app/../secret", "https://example.test/app")


def test_worker_timeout_still_runs_cleanup():
    cleaned = []
    worker = AssessmentWorker(timeout_seconds=0.01)
    with pytest.raises(TimeoutError):
        worker.run(lambda cancel: __import__("time").sleep(0.1), lambda: cleaned.append(True))
    assert cleaned == [True]


def test_deployed_auth_without_configuration_fails_closed():
    original = (settings.environment, settings.api_key)
    settings.environment, settings.api_key = "production", None
    try:
        from app.auth import require_auth
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            require_auth(None)
        assert error.value.status_code == 503
    finally:
        settings.environment, settings.api_key = original

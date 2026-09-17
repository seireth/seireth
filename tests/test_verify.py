"""Polling checks use a fake clock, avoiding slow and timing-dependent tests."""

import argparse

import httpx
import pytest

from app import verify


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(verify.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        verify.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds)
    )
    return now


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
def test_polling_waits_beyond_old_five_second_window(clock, terminal):
    def respond(request):
        status = terminal if clock[0] >= 6 else "running"
        return httpx.Response(200, json={"status": status, "result": None})

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        assert verify.wait_for_results(client, "assessment-1", 10)["status"] == terminal
    assert 6 <= clock[0] < 10


def test_polling_timeout_reports_id_and_last_state(clock):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "queued", "result": None})
    )
    with httpx.Client(base_url="http://test", transport=transport) as client:
        with pytest.raises(
            RuntimeError, match="assessment-1 did not finish within 1s.*queued"
        ):
            verify.wait_for_results(client, "assessment-1", 1)
    assert clock[0] == pytest.approx(1)


def test_polling_http_errors_are_not_hidden(clock):
    transport = httpx.MockTransport(lambda request: httpx.Response(403, text="denied"))
    with httpx.Client(base_url="http://test", transport=transport) as client:
        with pytest.raises(RuntimeError, match="403: denied"):
            verify.wait_for_results(client, "assessment-1", 1)


def test_request_timeout_includes_last_response(clock):
    def respond(request):
        if clock[0] == 0:
            return httpx.Response(200, json={"status": "running", "result": None})
        assert request.extensions["timeout"]["read"] <= 0.8
        raise httpx.ReadTimeout("slow server", request=request)

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(respond)
    ) as client:
        with pytest.raises(
            RuntimeError, match="assessment-1 polling request timed out.*running"
        ):
            verify.wait_for_results(client, "assessment-1", 1)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_timeout_is_rejected(value):
    with pytest.raises(argparse.ArgumentTypeError):
        verify.positive_timeout(value)

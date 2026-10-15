"""Scenario response metadata and redirect behavior over real HTTP."""

from dataclasses import replace
from threading import Thread

import httpx
import pytest

from examples.demo_app import server as demo_server
from examples.demo_app.scenarios import CSP_SCENARIOS, SCENARIOS


def assert_declared_metadata(response, scenario):
    assert response.status_code == scenario.status
    expected_types = (
        [] if scenario.content_type is None else [scenario.content_type]
    ) + [value for name, value in scenario.headers if name.lower() == "content-type"]
    assert response.headers.get_list("content-type") == expected_types


@pytest.fixture
def server():
    with demo_server.WorkspaceServer(("127.0.0.1", 0)) as workspace:
        thread = Thread(
            target=workspace.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{workspace.server_port}", timeout=5
            ) as client:
                yield client
        finally:
            workspace.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/tickets",
        "/account",
        "/login",
        "/api/tickets",
        "/assets/app.css",
        "/assets/app.js",
        "/errors/not-found",
        "/lab/json-unprotected",
    ],
)
def test_every_scenario_route_uses_its_configured_response(
    server, monkeypatch, method, path
):
    configured = replace(
        demo_server.BY_PATH[path],
        status=418,
        headers=(("X-Scenario-Test", "first"), ("X-Scenario-Test", "second")),
        content_type="text/plain; charset=utf-8",
    )
    monkeypatch.setitem(demo_server.BY_PATH, path, configured)
    response = server.request(method, path)
    assert response.status_code == 418
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers.get_list("x-scenario-test") == ["first", "second"]
    assert "content-security-policy" not in response.headers
    if method == "HEAD":
        assert response.content == b""


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize(
    "path",
    [
        "/lab/unknown-type",
        "/lab/malformed-type",
        "/lab/conflicting-types",
        "/lab/no-content",
    ],
)
def test_intentional_response_metadata_gaps_are_preserved(server, method, path):
    response = server.request(method, path)
    scenario = demo_server.BY_PATH[path]
    assert_declared_metadata(response, scenario)
    if method == "HEAD" or scenario.status == 204:
        assert response.content == b""


def test_login_redirect_preserves_status_and_destination(server):
    redirect = server.get("/login")
    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/account"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.path)
def test_scenarios_emit_declared_metadata(server, scenario):
    response = server.get(scenario.path)
    assert_declared_metadata(response, scenario)


@pytest.mark.parametrize("scenario", CSP_SCENARIOS, ids=lambda scenario: scenario.path)
def test_csp_scenarios_emit_separate_policy_fields(server, scenario):
    response = server.get(scenario.path)
    assert_declared_metadata(response, scenario)
    assert response.headers.get_list("content-security-policy") == [
        value
        for name, value in scenario.headers
        if name.lower() == "content-security-policy"
    ]
    assert "CSP policy findings:" in response.text


def test_baseline_scenario_does_not_invent_csp_expectations(server):
    response = server.get("/lab/csp-comma")
    assert "CSP policy findings:" not in response.text
    assert response.headers["content-security-policy"] == (
        "frame-ancestors *, frame-ancestors 'none'"
    )

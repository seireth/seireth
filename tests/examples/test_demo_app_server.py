"""Scenario configuration reaches real GET/HEAD responses and correct bodies."""

import json
from dataclasses import replace
from threading import Thread

import httpx
import pytest

from examples.demo_app import server as demo_server
from examples.demo_app.scenarios import SCENARIOS, Scenario


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


@pytest.mark.parametrize(
    "content_type", ["Application/JSON; Charset=UTF-8", " text/css ; charset=utf-8"]
)
def test_parameterized_lab_content_types_render_their_declared_body(
    server, monkeypatch, content_type
):
    scenario = Scenario(
        "/lab/parameterized",
        "Parameterized",
        "Fixture body",
        (),
        content_type=content_type,
    )
    monkeypatch.setitem(demo_server.BY_PATH, scenario.path, scenario)
    response = server.get(scenario.path)
    if content_type.lower().startswith("application/json"):
        assert response.json() == {
            "scenario": "Parameterized",
            "description": "Fixture body",
        }
    else:
        assert response.text.startswith("/* Header applicability demo. */")
    assert "<!doctype html>" not in response.text


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


def test_specialized_route_bodies_and_redirect_destination_are_preserved(server):
    tickets = server.get("/api/tickets")
    assert (
        json.loads(tickets.content)["items"][0]["title"]
        == "Review the release checklist"
    )
    assert (
        server.get("/assets/app.css").content
        == (demo_server.STATIC / "app.css").read_bytes()
    )
    assert (
        server.get("/assets/app.js").content
        == (demo_server.STATIC / "app.js").read_bytes()
    )
    redirect = server.get("/login")
    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/account"
    assert "Continue to your workspace" in redirect.text


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.path)
def test_scenarios_emit_declared_metadata(server, scenario):
    response = server.get(scenario.path)
    assert_declared_metadata(response, scenario)

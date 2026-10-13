"""Controlled website acceptance, frozen configuration, and safe request bounds."""

import json
from threading import Event
from time import monotonic

import pytest

from app.assessments import http_fetch
from app.assessments.execution import ExecutionContext
from app.assessments.plans import RoutePlan, freeze_plan
from app.assessments.policy import PolicyError
from app.assessments.profiles import OperatorConfig, public_catalog
from app.assessments.website import WebsiteSession
from app.plugins.base import AnalysisContext
from app.plugins.cookie_security import analyze
from tests.website import configure, graph


def test_native_fetch_reaches_actual_site_with_auth_and_preserved_host(
    monkeypatch, tmp_path, website
):
    configure(monkeypatch, tmp_path, website)
    project, target = graph(website)
    route = RoutePlan(
        key="private",
        url=website.url + "private",
        plugins=["http-security-headers"],
        request_profile="authenticated",
    )
    snapshot = freeze_plan(project, target, [route])
    assert "fixture-secret" not in json.dumps(snapshot)
    context = ExecutionContext(Event(), Event(), monotonic() + 5)
    session = WebsiteSession(snapshot, context)
    session.prepare()
    response = session.fetch(snapshot["routes"][0])
    assert response["observation"].status_code == 200
    assert website.handler.requests == [
        ("/private", "Bearer fixture-secret", website.url.split("//")[1].rstrip("/"))
    ]
    assert session.cleanup().verified


@pytest.mark.parametrize(
    "addresses",
    [["127.0.0.1"], ["169.254.169.254"], ["fd00:ec2::254"], ["1.1.1.1", "127.0.0.1"]],
)
def test_public_target_cannot_connect_to_private_or_metadata_addresses(addresses):
    snapshot = {
        "target": {
            "url": "https://example.test/",
            "network_profile": None,
            "trust_profile": None,
        },
        "network": None,
        "control_endpoints": [],
    }
    authorize = http_fetch.website_authorizer(
        snapshot, lambda: OperatorConfig(), ("http", "127.0.0.1", 8000)
    )
    with pytest.raises(PolicyError):
        authorize("example.test", 443, addresses)


def test_network_permission_revocation_applies_to_frozen_plan(
    monkeypatch, tmp_path, website
):
    path = configure(monkeypatch, tmp_path, website)
    project, target = graph(website)
    snapshot = freeze_plan(
        project,
        target,
        [RoutePlan(key="root", url=website.url, plugins=["http-security-headers"])],
    )
    path.write_text("{}")
    session = WebsiteSession(
        snapshot, ExecutionContext(Event(), Event(), monotonic() + 5)
    )
    session.prepare()
    with pytest.raises(PolicyError):
        session.fetch(snapshot["routes"][0])
    assert website.handler.requests == []
    assert session.cleanup().verified


def test_redirect_connection_rechecks_current_network_permission(
    monkeypatch, tmp_path, website, execution_context
):
    path = configure(monkeypatch, tmp_path, website)
    config = json.loads(path.read_text())
    config["requests"]["follow"] = {"follow_redirects": True}
    path.write_text(json.dumps(config))
    project, target = graph(website)
    snapshot = freeze_plan(
        project,
        target,
        [
            RoutePlan(
                key="private",
                url=website.url + "private",
                plugins=["http-security-headers"],
                request_profile="follow",
            )
        ],
    )
    original = website.handler.do_GET

    def revoke_before_response(handler):
        path.write_text("{}")
        original(handler)

    monkeypatch.setattr(website.handler, "do_GET", revoke_before_response)
    session = WebsiteSession(snapshot, execution_context)
    session.prepare()
    with pytest.raises(PolicyError, match="active network grant"):
        session.fetch(snapshot["routes"][0])
    assert [request[0] for request in website.handler.requests] == ["/private"]
    assert session.cleanup().verified


def test_timeout_closes_native_fetch_and_does_not_replay(
    monkeypatch, tmp_path, website
):
    configure(monkeypatch, tmp_path, website)
    project, target = graph(website)
    snapshot = freeze_plan(
        project,
        target,
        [
            RoutePlan(
                key="slow",
                url=website.url + "slow",
                plugins=["http-security-headers"],
                request_seconds=0.05,
            )
        ],
    )
    session = WebsiteSession(
        snapshot, ExecutionContext(Event(), Event(), monotonic() + 5)
    )
    session.prepare()
    with pytest.raises(TimeoutError):
        session.fetch(snapshot["routes"][0])
    assert session.cleanup().verified
    assert len(website.handler.requests) <= 1


def test_request_definitions_are_frozen_but_secrets_are_runtime_references(
    monkeypatch, tmp_path, website
):
    path = configure(monkeypatch, tmp_path, website)
    project, target = graph(website)
    snapshot = freeze_plan(
        project,
        target,
        [
            RoutePlan(
                key="private",
                url=website.url + "private",
                plugins=["http-security-headers"],
                request_profile="authenticated",
            )
        ],
    )
    config = json.loads(path.read_text())
    config["requests"]["authenticated"] = {"headers": {"X-Changed": "changed"}}
    path.write_text(json.dumps(config))
    monkeypatch.setenv("FIXTURE_SESSION", "Bearer rotated-secret")
    session = WebsiteSession(
        snapshot, ExecutionContext(Event(), Event(), monotonic() + 5)
    )
    session.prepare()
    assert session.headers["private"] == {"Authorization": "Bearer rotated-secret"}
    assert "rotated-secret" not in json.dumps(public_catalog())


def test_session_checks_are_explicit_and_redacted():
    from app.plugins.base import HttpObservation

    observation = HttpObservation(
        url="https://fixture.test/",
        status_code=200,
        headers={"set-cookie": ["session=secret; Path=/"]},
    )
    assert analyze(observation, AnalysisContext()).findings == ()
    result = analyze(
        observation,
        AnalysisContext(session_cookies=("session",), expected_cookies=("session",)),
    )
    assert len(result.findings) == 2
    assert "secret" not in result.model_dump_json()
    assert [check.status for check in result.checks][-3:] == [
        "failed",
        "failed",
        "passed",
    ]


@pytest.mark.parametrize("stop", ["route-timeout", "deadline", "cancelled"])
def test_later_failure_does_not_keep_an_earlier_failed_plugin(
    monkeypatch, make_plugin, execution_context, stop
):
    from app.assessments import workflows
    from app.assessments.sandbox import CleanupOutcome
    from app.plugins.base import HttpObservation
    from app.plugins.registry import PluginRegistry

    def broken(observation, _analysis):
        raise RuntimeError("private plugin diagnostic")

    monkeypatch.setattr(
        workflows, "registry", PluginRegistry((make_plugin("broken", broken),))
    )
    records = []

    class Session:
        def prepare(self):
            pass

        def fetch(self, route):
            if records:
                raise TimeoutError()
            return {
                "observation": HttpObservation(
                    url=route["url"], status_code=200, headers={}
                ),
                "redirects": [],
            }

        def cleanup(self):
            return CleanupOutcome(True)

    def persist(data):
        records.append(data)
        if stop == "cancelled":
            execution_context.cancel.set()
        elif stop == "deadline":
            execution_context.deadline = monotonic() - 1

    routes = [
        {
            "key": key,
            "url": "https://fixture.test/",
            "plugins": ["broken"],
            "analysis": {},
        }
        for key in ("first", "second")
    ]
    outcome = workflows.execute_plan(
        Session(), {"routes": routes}, execution_context, persist
    )
    assert records[0]["failed_plugin"] == "broken"
    assert records[1]["status"] == (
        "failed" if stop == "route-timeout" else "unattempted"
    )
    assert outcome.status == ("cancelled" if stop == "cancelled" else "failed")
    assert outcome.error_kind == (None if stop == "cancelled" else "timeout")
    assert outcome.failed_plugin is None
    assert outcome.cleanup_verified

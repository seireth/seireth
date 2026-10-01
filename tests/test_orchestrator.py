"""Shared fetching, plugin execution, and cleanup."""

import pytest

from app.orchestrator import execute
from app.plugins.base import HttpObservation, PluginFinding, PluginResponse
from app.plugins.security_headers import PLUGIN as SECURITY_HEADERS_PLUGIN
from app.sandbox import CleanupOutcome

URL = "http://demo-target:8080/"


@pytest.fixture
def recording_sandbox():
    calls = []

    class Sandbox:
        observation = HttpObservation(
            url=URL, headers={"Set-Cookie": ["theme=synthetic-cookie"]}
        )

        def execute(self, url):
            calls.append("fetch")
            assert str(self.observation.url) == url
            return self.observation

        def cleanup(self):
            calls.append("cleanup")
            return CleanupOutcome(True)

    return Sandbox(), calls


def test_multiple_plugins_share_one_fetch_but_not_mutable_observations(
    recording_sandbox, make_plugin, execution_context
):
    sandbox, calls = recording_sandbox

    def first(observation):
        observation.headers["set-cookie"].append("mutated=synthetic-cookie")
        calls.append("first")
        return PluginResponse(findings=())

    def second(observation):
        assert observation.headers["set-cookie"] == ["theme=synthetic-cookie"]
        calls.append("second")
        return PluginResponse(findings=())

    plugins = [make_plugin("first", first), make_plugin("second", second)]
    outcome = execute(sandbox, URL, execution_context, plugins)
    assert outcome.status == "completed"
    assert [item.plugin_id for item in outcome.plugin_results] == ["first", "second"]
    assert calls == ["fetch", "first", "second", "cleanup"]
    assert sandbox.observation.headers == {"set-cookie": ["theme=synthetic-cookie"]}


@pytest.mark.parametrize("mode", ["raises", "invalid-response"])
def test_plugin_error_fails_attempt_but_still_cleans_up(
    mode, recording_sandbox, make_plugin, execution_context, caplog
):
    sandbox, calls = recording_sandbox

    observations = []

    def broken(observation):
        observations.append(observation)
        calls.append("broken")
        if mode == "raises":
            raise RuntimeError("plugin failed")
        return object()

    outcome = execute(sandbox, URL, execution_context, [make_plugin("broken", broken)])
    assert outcome.status == "failed"
    assert outcome.cleanup_verified
    assert outcome.plugin_results == []
    assert calls == ["fetch", "broken", "cleanup"]
    assert len(observations) == 1
    assert str(observations[0].url) == URL
    assert observations[0].headers == {"set-cookie": ["theme=synthetic-cookie"]}
    assert (
        "plugin broken returned an invalid response"
        if mode == "invalid-response"
        else "plugin failed"
    ) in caplog.text


@pytest.mark.parametrize("field", ["description", "remediation"])
@pytest.mark.parametrize("bypass_validation", [False, True])
def test_blank_finding_fails_only_its_attempt_and_cleans_up(
    field,
    bypass_validation,
    recording_sandbox,
    finding_payload,
    make_plugin,
    execution_context,
    caplog,
):
    sandbox, calls = recording_sandbox
    observations = []

    def broken(observation):
        observations.append(observation)
        calls.append("broken")
        values = finding_payload
        values[field] = " \t\n\u2003"
        if bypass_validation:
            finding = PluginFinding.model_construct(**values)
            return PluginResponse.model_construct(findings=(finding,))
        return PluginResponse(findings=(PluginFinding(**values),))

    outcome = execute(sandbox, URL, execution_context, [make_plugin("broken", broken)])
    assert outcome.status == "failed"
    assert outcome.cleanup_verified
    assert outcome.plugin_results == []
    assert calls == ["fetch", "broken", "cleanup"]
    assert len(observations) == 1
    assert str(observations[0].url) == URL
    assert observations[0].headers == {"set-cookie": ["theme=synthetic-cookie"]}
    assert (
        "plugin broken returned an invalid response" if bypass_validation else field
    ) in caplog.text

    other = execute(sandbox, URL, execution_context, [SECURITY_HEADERS_PLUGIN])
    assert other.status == "completed"
    assert other.cleanup_verified
    assert len(other.plugin_results[0].findings) == 3
    assert calls == ["fetch", "broken", "cleanup", "fetch", "cleanup"]


def test_cleanup_exception_fails_successful_analysis(
    recording_sandbox, make_plugin, execution_context, monkeypatch, caplog
):
    sandbox, calls = recording_sandbox

    def analyze(observation):
        calls.append("analyze")
        return PluginResponse(findings=())

    def cleanup():
        calls.append("cleanup")
        raise OSError("synthetic cleanup failure")

    monkeypatch.setattr(sandbox, "cleanup", cleanup)
    outcome = execute(sandbox, URL, execution_context, [make_plugin("valid", analyze)])
    assert calls == ["fetch", "analyze", "cleanup"]
    assert outcome.status == "failed"
    assert not outcome.cleanup_verified
    assert outcome.cleanup_reason == "cleanup could not be completed"
    assert outcome.error == "sandbox cleanup could not be verified"
    assert "synthetic cleanup failure" in caplog.text

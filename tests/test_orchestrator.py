"""Shared fetching, plugin execution, and cleanup."""

from threading import Event
from time import monotonic

import pytest

from app.execution import ExecutionContext
from app.orchestrator import execute
from app.plugins.base import PluginFinding, PluginResponse
from app.plugins.security_headers import PLUGIN as SECURITY_HEADERS_PLUGIN
from app.sandbox import CleanupOutcome

URL = "http://demo-target:8080/"


@pytest.fixture
def recording_sandbox():
    calls = []

    class Sandbox:
        def execute(self, url):
            calls.append("fetch")
            return {}

        def cleanup(self):
            calls.append("cleanup")
            return CleanupOutcome(True)

    return Sandbox(), calls


def test_multiple_plugins_share_one_fetch_but_not_mutable_observations(
    recording_sandbox, make_plugin
):
    sandbox, calls = recording_sandbox

    def first(observation):
        observation.headers["mutated"] = "yes"
        calls.append("first")
        return PluginResponse(findings=())

    def second(observation):
        assert "mutated" not in observation.headers
        calls.append("second")
        return PluginResponse(findings=())

    plugins = [make_plugin("first", first), make_plugin("second", second)]
    context = ExecutionContext(Event(), Event(), monotonic() + 5)
    outcome = execute(sandbox, URL, context, plugins)
    assert outcome.status == "completed"
    assert [item.plugin_id for item in outcome.plugin_results] == ["first", "second"]
    assert calls == ["fetch", "first", "second", "cleanup"]


@pytest.mark.parametrize("mode", ["raises", "invalid-response"])
def test_plugin_error_fails_attempt_but_still_cleans_up(
    mode, recording_sandbox, make_plugin
):
    sandbox, calls = recording_sandbox

    def broken(observation):
        if mode == "raises":
            raise RuntimeError("plugin failed")
        return object()

    context = ExecutionContext(Event(), Event(), monotonic() + 5)
    outcome = execute(sandbox, URL, context, [make_plugin("broken", broken)])
    assert outcome.status == "failed"
    assert outcome.cleanup_verified
    assert outcome.plugin_results == []
    assert calls == ["fetch", "cleanup"]


@pytest.mark.parametrize("field", ["description", "remediation"])
@pytest.mark.parametrize("bypass_validation", [False, True])
def test_blank_finding_fails_only_its_attempt_and_cleans_up(
    field, bypass_validation, recording_sandbox, finding_payload, make_plugin
):
    sandbox, calls = recording_sandbox

    def broken(observation):
        values = finding_payload
        values[field] = " \t\n\u2003"
        if bypass_validation:
            finding = PluginFinding.model_construct(**values)
            return PluginResponse.model_construct(findings=(finding,))
        return PluginResponse(findings=(PluginFinding(**values),))

    context = ExecutionContext(Event(), Event(), monotonic() + 5)
    outcome = execute(sandbox, URL, context, [make_plugin("broken", broken)])
    assert outcome.status == "failed"
    assert outcome.cleanup_verified
    assert outcome.plugin_results == []
    assert calls == ["fetch", "cleanup"]

    other_context = ExecutionContext(Event(), Event(), monotonic() + 5)
    other = execute(sandbox, URL, other_context, [SECURITY_HEADERS_PLUGIN])
    assert other.status == "completed"
    assert other.cleanup_verified
    assert len(other.plugin_results[0].findings) == 3
    assert calls == ["fetch", "cleanup", "fetch", "cleanup"]

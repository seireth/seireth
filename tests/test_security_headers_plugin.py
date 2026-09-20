"""Observable behavior of the first built-in plugin and its registry."""

from threading import Event
from time import monotonic

import pytest

from app.execution import ExecutionContext
from app.orchestrator import execute
from app.plugins import BY_ID, Plugin, select_plugins
from app.plugins.security_headers import security_headers
from app.sandbox import CleanupOutcome

URL = "http://demo-target:8080/"


def finding_headers(headers):
    return {finding.evidence["header"] for finding in security_headers(headers, URL)}


@pytest.mark.parametrize("value", ["nosniff", "NoSniff", " nosniff "])
def test_nosniff_value_is_accepted(value):
    assert "x-content-type-options" not in finding_headers(
        {"X-Content-Type-Options": value}
    )


@pytest.mark.parametrize("value", [None, "", "invalid", "nosniff, other"])
def test_missing_or_ineffective_nosniff_is_reported(value):
    headers = {} if value is None else {"X-Content-Type-Options": value}
    assert "x-content-type-options" in finding_headers(headers)


@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_or_blank_csp_is_reported(value):
    headers = {} if value is None else {"Content-Security-Policy": value}
    assert "content-security-policy" in finding_headers(headers)


def test_nonblank_csp_is_accepted_without_claiming_full_validation():
    assert "content-security-policy" not in finding_headers(
        {"Content-Security-Policy": "default-src 'self'"}
    )


@pytest.mark.parametrize("value", ["DENY", "sameorigin", " SameOrigin "])
def test_supported_frame_option_is_accepted(value):
    assert "x-frame-options" not in finding_headers({"X-Frame-Options": value})


@pytest.mark.parametrize("value", [None, "", "ALLOW-FROM example.com", "invalid"])
def test_missing_or_ineffective_frame_option_is_reported(value):
    headers = {} if value is None else {"X-Frame-Options": value}
    assert "x-frame-options" in finding_headers(headers)


def test_enforced_frame_ancestors_replaces_frame_option():
    assert "x-frame-options" not in finding_headers(
        {"Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'"}
    )
    assert "x-frame-options" not in finding_headers(
        {"Content-Security-Policy": "frame-ancestors 'self' https://trusted.test"}
    )
    assert "x-frame-options" in finding_headers(
        {"Content-Security-Policy-Report-Only": "frame-ancestors 'none'"}
    )
    assert "x-frame-options" in finding_headers(
        {"Content-Security-Policy": "frame-ancestors *"}
    )
    assert "x-frame-options" in finding_headers(
        {"Content-Security-Policy": "frame-ancestors invalid-source"}
    )
    assert "x-frame-options" in finding_headers(
        {"Content-Security-Policy": "frame-ancestors *; frame-ancestors 'none'"}
    )


def test_every_finding_has_actionable_remediation():
    assert len(security_headers({}, URL)) == 3
    assert all(finding.remediation for finding in security_headers({}, URL))


def test_plugin_selection_rejects_invalid_lists():
    for ids in ([], ["missing"], ["security-headers", "security-headers"]):
        with pytest.raises(ValueError):
            select_plugins(ids, "passive")
    assert [plugin.id for plugin in select_plugins(None, "passive")] == [
        "security-headers"
    ]


def test_multiple_plugins_share_one_observation_and_cleanup(monkeypatch):
    calls = []

    class Sandbox:
        def execute(self, url):
            calls.append("fetch")
            return {}

        def cleanup(self):
            calls.append("cleanup")
            return CleanupOutcome(True)

    def second(headers, url):
        calls.append("second")
        return []

    monkeypatch.setitem(
        BY_ID,
        "second",
        Plugin("second", "Second", "Test second plugin", ("passive",), second),
    )
    context = ExecutionContext(Event(), Event(), monotonic() + 5)
    outcome = execute(Sandbox(), URL, context, ["security-headers", "second"])
    assert outcome.status == "completed"
    assert [item.plugin_id for item in outcome.plugin_results] == [
        "security-headers",
        "second",
    ]
    assert calls == ["fetch", "second", "cleanup"]


def test_plugin_error_fails_attempt_but_still_cleans_up(monkeypatch):
    calls = []

    class Sandbox:
        def execute(self, url):
            calls.append("fetch")
            return {}

        def cleanup(self):
            calls.append("cleanup")
            return CleanupOutcome(True)

    def broken(headers, url):
        raise RuntimeError("plugin failed")

    monkeypatch.setitem(
        BY_ID,
        "broken",
        Plugin("broken", "Broken", "Test failure", ("passive",), broken),
    )
    context = ExecutionContext(Event(), Event(), monotonic() + 5)
    outcome = execute(Sandbox(), URL, context, ["security-headers", "broken"])
    assert outcome.status == "failed"
    assert outcome.cleanup_verified
    assert calls == ["fetch", "cleanup"]

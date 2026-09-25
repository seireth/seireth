"""Built-in security-header analysis."""

import pytest

from app.plugins.base import HttpObservation
from app.plugins.security_headers import analyze

URL = "http://demo-target:8080/"


def response(headers):
    return analyze(HttpObservation(url=URL, headers=headers))


def finding_headers(headers):
    return {finding.evidence["header"] for finding in response(headers).findings}


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


@pytest.mark.parametrize(
    "value, report_only, replaces_frame_option",
    [
        ("default-src 'self'; frame-ancestors 'none'", False, True),
        ("frame-ancestors 'self' https://trusted.test", False, True),
        ("frame-ancestors 'none'", True, False),
        ("frame-ancestors *", False, False),
        ("frame-ancestors invalid-source", False, False),
        ("frame-ancestors *; frame-ancestors 'none'", False, False),
    ],
    ids=[
        "deny-all",
        "trusted-origins",
        "report-only",
        "wildcard",
        "invalid-source",
        "duplicate-directive",
    ],
)
def test_enforced_frame_ancestors_replaces_frame_option(
    value, report_only, replaces_frame_option
):
    header = "Content-Security-Policy" + ("-Report-Only" if report_only else "")
    assert (
        "x-frame-options" not in finding_headers({header: value})
    ) is replaces_frame_option


def test_every_finding_has_actionable_remediation():
    findings = response({}).findings
    assert len(findings) == 3
    assert all(finding.remediation for finding in findings)

"""Built-in security-header analysis."""

import pytest

from app.plugins.base import HttpObservation
from app.plugins.security_headers import analyze

URL = "http://demo-target:8080/"


def response(headers):
    return analyze(
        HttpObservation(
            url=URL, headers={name: [value] for name, value in headers.items()}
        )
    )


def finding_headers(headers):
    return {finding.evidence["header"] for finding in response(headers).findings}


@pytest.mark.parametrize(
    "value", ["nosniff", "NoSniff", " nosniff ", "nosniff, other", "nosniff,"]
)
def test_nosniff_value_is_accepted(value):
    assert "x-content-type-options" not in finding_headers(
        {"X-Content-Type-Options": value}
    )


@pytest.mark.parametrize(
    "value",
    [None, "", "invalid", "other, nosniff", ",nosniff", '"nosniff"', "\u00a0nosniff"],
)
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
    assert {finding.evidence["header"] for finding in findings} == {
        "x-content-type-options",
        "content-security-policy",
        "x-frame-options",
    }
    assert all(
        finding.evidence == {"url": URL, "header": finding.evidence["header"]}
        for finding in findings
    )


def test_protected_response_with_mixed_case_header_names_has_no_findings():
    assert (
        response(
            {
                "x-CoNtEnT-tYpE-oPtIoNs": "NoSniff",
                "CONTENT-security-POLICY": "default-src 'self'",
                "x-FRAME-options": "DENY",
            }
        ).findings
        == ()
    )


@pytest.mark.parametrize(
    "values,reported",
    [
        (["invalid", "nosniff"], True),
        (["nosniff", "invalid"], False),
        (["", "nosniff"], True),
        (["nosniff", ""], False),
        (['"other, nosniff"'], True),
        (['"other, nosniff'], True),
    ],
)
def test_nosniff_uses_first_parsed_value(values, reported):
    response = analyze(
        HttpObservation(url=URL, headers={"X-Content-Type-Options": values})
    )
    assert (
        "x-content-type-options"
        in {item.evidence["header"] for item in response.findings}
    ) is reported


@pytest.mark.parametrize(
    "policies",
    [
        ["frame-ancestors 'none'", "default-src 'self'"],
        ["default-src 'self'", "frame-ancestors 'none'"],
        ["frame-ancestors 'none'", ""],
        ["frame-ancestors 'none', default-src 'self'"],
        ["frame-ancestors *, frame-ancestors 'none'"],
        ["frame-ancestors 'none'; frame-ancestors *"],
        ["frame-ancestors"],
    ],
)
def test_restrictive_enforced_policy_provides_framing_protection(policies):
    result = analyze(
        HttpObservation(url=URL, headers={"Content-Security-Policy": policies})
    )
    assert "x-frame-options" not in {
        item.evidence["header"] for item in result.findings
    }


@pytest.mark.parametrize(
    "policy",
    [
        "frame-ancestors *",
        "frame-ancestors *; frame-ancestors 'none'",
        "frame-ancestors invalid-source",
    ],
)
def test_enforced_frame_ancestors_overrides_deny_even_without_recognized_protection(
    policy,
):
    result = analyze(
        HttpObservation(
            url=URL,
            headers={
                "Content-Security-Policy": [policy],
                "X-Frame-Options": ["DENY"],
            },
        )
    )
    assert "x-frame-options" in {item.evidence["header"] for item in result.findings}


def test_report_only_frame_ancestors_does_not_override_deny():
    result = analyze(
        HttpObservation(
            url=URL,
            headers={
                "Content-Security-Policy-Report-Only": ["frame-ancestors *"],
                "X-Frame-Options": ["DENY"],
            },
        )
    )
    assert {item.evidence["header"] for item in result.findings} == {
        "x-content-type-options",
        "content-security-policy",
    }


@pytest.mark.parametrize(
    "values,reported",
    [
        (["SAMEORIGIN", "SAMEORIGIN"], False),
        (["SAMEORIGIN, DENY"], False),
        (["SAMEORIGIN,"], False),
        (["INVALID", "DENY"], False),
        (["DENY", "INVALID"], False),
        (["ALLOWALL, INVALID"], False),
        (["ALLOWALL,"], False),
        (["INVALID, INVALID"], True),
        (['"INVALID, DENY"'], True),
        (['"INVALID, DENY'], True),
        (['"DENY"'], True),
        ([r'"INVALID\", DENY", SAMEORIGIN'], False),
    ],
)
def test_repeated_frame_options_and_quoted_values_follow_browser_rules(
    values, reported
):
    result = analyze(HttpObservation(url=URL, headers={"X-Frame-Options": values}))
    assert (
        "x-frame-options" in {item.evidence["header"] for item in result.findings}
    ) is reported

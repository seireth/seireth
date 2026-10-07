"""Built-in security-header analysis."""

import pytest

from app.api.schemas import HeaderEvidenceData
from app.plugins.base import HttpObservation
from app.plugins.http_security_headers import analyze
from examples.demo_app.scenarios import SCENARIOS

URL = "http://demo-app:8080/"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.path)
def test_demo_scenarios_keep_independent_outcomes_and_valid_evidence(scenario):
    headers = {}
    if scenario.content_type is not None:
        headers["Content-Type"] = [scenario.content_type]
    for name, value in scenario.headers:
        headers.setdefault(name, []).append(value)
    result = response(headers, status_code=scenario.status, media_type=None)
    assert tuple(check.status for check in result.checks) == scenario.expected_checks
    assert (
        tuple(finding.evidence["rule_id"] for finding in result.findings)
        == scenario.expected
    )
    for finding in result.findings:
        assert (
            HeaderEvidenceData.model_validate(finding.evidence).model_dump(mode="json")
            == finding.evidence
        )


@pytest.mark.parametrize(
    "status,media,outcomes",
    [
        (200, "text/html", ("failed", "failed", "failed")),
        (404, "application/xhtml+xml", ("failed", "failed", "failed")),
        (503, "text/html", ("failed", "failed", "failed")),
        *[
            (200, media, ("failed", "skipped", "skipped"))
            for media in [
                "application/json",
                "application/problem+json",
                "text/javascript",
                "application/javascript",
                "text/css",
                "text/plain",
                "image/png",
            ]
        ],
        *[
            (status, "text/html", ("skipped",) * 3)
            for status in [101, 204, 205, 301, 302, 303, 304, 307, 308]
        ],
        *[
            (200, media, ("failed", "inconclusive", "inconclusive"))
            for media in [None, "invalid", "application/pdf", "image/svg+xml"]
        ],
    ],
)
def test_response_applicability_is_visible_without_false_findings(
    status, media, outcomes
):
    headers = {} if media is None else {"Content-Type": [media]}
    result = response(headers, status_code=status, media_type=None)
    assert [check.rule_id for check in result.checks] == [
        "x-content-type-options",
        "content-security-policy",
        "framing-protection",
    ]
    assert tuple(check.status for check in result.checks) == outcomes
    assert all(check.reason.strip() for check in result.checks)
    assert len(result.findings) == outcomes.count("failed")
    assert {finding.evidence["rule_id"] for finding in result.findings} == {
        check.rule_id for check in result.checks if check.status == "failed"
    }


def test_conflicting_content_types_do_not_guess_document_applicability():
    result = response(
        {
            "Content-Type": ["text/html", "application/json"],
            "X-Content-Type-Options": ["nosniff"],
        },
        status_code=200,
        media_type=None,
    )
    assert [check.status for check in result.checks] == [
        "passed",
        "inconclusive",
        "inconclusive",
    ]
    assert result.findings == ()


def test_header_evidence_uses_safe_conditions_not_raw_values():
    result = response(
        {
            "Content-Type": ["TEXT/HTML; charset=UTF-8"],
            "X-Content-Type-Options": ["synthetic-secret-nosniff"],
            "Content-Security-Policy": [
                "script-src 'nonce-synthetic-secret'; frame-ancestors *"
            ],
            "Set-Cookie": ["session=synthetic-secret-cookie"],
        },
        status_code=404,
        media_type=None,
    )
    assert "synthetic-secret" not in result.model_dump_json()
    assert [finding.evidence["condition"] for finding in result.findings] == [
        "unrecognized",
        "unrestricted",
    ]
    assert result.findings[-1].evidence["header"] == "content-security-policy"
    assert result.findings[-1].evidence["rule_id"] == "framing-protection"
    assert all(finding.evidence["status_code"] == 404 for finding in result.findings)
    assert all(
        finding.evidence["media_type"] == "text/html" for finding in result.findings
    )


def response(headers, *, status_code=200, media_type="text/html"):
    fields = {
        name: [value] if isinstance(value, str) else value
        for name, value in headers.items()
    }
    if media_type is not None and not any(
        name.lower() == "content-type" for name in fields
    ):
        fields["Content-Type"] = [media_type]
    return analyze(
        HttpObservation(
            status_code=status_code,
            url=URL,
            headers=fields,
        )
    )


def finding_rules(headers):
    return {finding.evidence["rule_id"] for finding in response(headers).findings}


@pytest.mark.parametrize(
    "value", ["nosniff", "NoSniff", " nosniff ", "nosniff, other", "nosniff,"]
)
def test_nosniff_value_is_accepted(value):
    assert "x-content-type-options" not in finding_rules(
        {"X-Content-Type-Options": value}
    )


@pytest.mark.parametrize(
    "value",
    [None, "", "invalid", "other, nosniff", ",nosniff", '"nosniff"', "\u00a0nosniff"],
)
def test_missing_or_ineffective_nosniff_is_reported(value):
    headers = {} if value is None else {"X-Content-Type-Options": value}
    assert "x-content-type-options" in finding_rules(headers)


@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_or_blank_csp_is_reported(value):
    headers = {} if value is None else {"Content-Security-Policy": value}
    assert "content-security-policy" in finding_rules(headers)


def test_nonblank_csp_is_accepted_without_claiming_full_validation():
    assert "content-security-policy" not in finding_rules(
        {"Content-Security-Policy": "default-src 'self'"}
    )


@pytest.mark.parametrize("value", ["DENY", "sameorigin", " SameOrigin "])
def test_supported_frame_option_is_accepted(value):
    assert "framing-protection" not in finding_rules({"X-Frame-Options": value})


@pytest.mark.parametrize("value", [None, "", "ALLOW-FROM example.com", "invalid"])
def test_missing_or_ineffective_frame_option_is_reported(value):
    headers = {} if value is None else {"X-Frame-Options": value}
    assert "framing-protection" in finding_rules(headers)


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
        "framing-protection" not in finding_rules({header: value})
    ) is replaces_frame_option


def test_every_finding_has_actionable_remediation():
    findings = response({}).findings
    assert len(findings) == 3
    assert all(finding.remediation for finding in findings)
    assert {finding.evidence["rule_id"] for finding in findings} == {
        "x-content-type-options",
        "content-security-policy",
        "framing-protection",
    }
    assert all(finding.evidence["url"] == URL for finding in findings)
    assert all(finding.evidence["status_code"] == 200 for finding in findings)
    assert all(finding.evidence["media_type"] == "text/html" for finding in findings)
    assert all(finding.evidence["condition"] == "missing" for finding in findings)
    assert all(finding.evidence["expected"] for finding in findings)


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
    result = response({"X-Content-Type-Options": values})
    assert (
        "x-content-type-options"
        in {item.evidence["rule_id"] for item in result.findings}
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
    result = response({"Content-Security-Policy": policies})
    assert "framing-protection" not in {
        item.evidence["rule_id"] for item in result.findings
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
    result = response(
        {"Content-Security-Policy": [policy], "X-Frame-Options": ["DENY"]}
    )
    assert "framing-protection" in {
        item.evidence["rule_id"] for item in result.findings
    }


def test_report_only_frame_ancestors_does_not_override_deny():
    result = response(
        {
            "Content-Security-Policy-Report-Only": ["frame-ancestors *"],
            "X-Frame-Options": ["DENY"],
        }
    )
    assert {item.evidence["rule_id"] for item in result.findings} == {
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
    result = response({"X-Frame-Options": values})
    assert (
        "framing-protection" in {item.evidence["rule_id"] for item in result.findings}
    ) is reported

"""Independent CSP expectations, conservative boundaries, and bounded input."""

import json

import pytest

from app.api.schemas import CspEvidenceData
from app.plugins.base import AnalysisContext, HttpObservation
from app.plugins.csp_policy import PLUGIN, analyze

URL = "https://example.test/"
RULES = ("csp-script-sources", "csp-inline-scripts", "csp-eval")
PASS = ("passed",) * 3
FAIL = ("failed",) * 3
PERMISSIVE = "script-src https: 'unsafe-inline' 'unsafe-eval'"


def response(*policies, status=200, content_type="text/html", extra=None):
    headers = {"content-security-policy": list(policies)} if policies else {}
    if content_type is not None:
        headers["content-type"] = [content_type]
    headers.update(extra or {})
    return HttpObservation(url=URL, status_code=status, headers=headers)


def assert_checks(observation, expected):
    result = analyze(observation, AnalysisContext())
    assert tuple(check.rule_id for check in result.checks) == RULES
    assert tuple(check.status for check in result.checks) == expected
    assert all(check.reason.strip() for check in result.checks)
    assert len(result.findings) == expected.count("failed")
    for finding in result.findings:
        data = CspEvidenceData.model_validate(finding.evidence)
        assert data.rule_id in RULES
        assert expected[RULES.index(data.rule_id)] == "failed"
    return result


@pytest.mark.parametrize(
    "policy,expected",
    [
        (PERMISSIVE, FAIL),
        ("frame-ancestors 'none'", FAIL),
        ("script-src", PASS),
        ("default-src", PASS),
        ("script-src 'none'", PASS),
        ("script-src 'self'", PASS),
        ("default-src 'self'", PASS),
        ("script-src https://cdn.example.test", PASS),
        ("script-src *.example.test", PASS),
        ("script-src *", ("failed", "passed", "passed")),
        ("script-src HTTP:", ("failed", "passed", "passed")),
        ("script-src HTTPS:", ("failed", "passed", "passed")),
        ("script-src https://*", ("failed", "passed", "passed")),
        ("script-src http://*", ("failed", "passed", "passed")),
        ("script-src https: 'nonce-YWJj'", ("failed", "passed", "passed")),
        (
            "script-src https: 'unsafe-inline' 'nonce-YWJj'",
            ("failed", "passed", "passed"),
        ),
        (
            "script-src https: 'unsafe-inline' 'sha256-YWJj'",
            ("failed", "passed", "passed"),
        ),
        (
            "script-src https: 'unsafe-inline' 'sha384-YWJj'",
            ("failed", "passed", "passed"),
        ),
        (
            "script-src https: 'unsafe-inline' 'sha512-YWJj'",
            ("failed", "passed", "passed"),
        ),
        ("script-src 'unsafe-inline' 'unsafe-hashes'", ("passed", "failed", "passed")),
        ("script-src https: 'unsafe-inline' 'strict-dynamic'", PASS),
        ("script-src 'nonce-YWJj' 'strict-dynamic' https: 'unsafe-inline'", PASS),
        ("script-src 'strict-dynamic' 'unsafe-eval'", ("passed", "passed", "failed")),
        ("script-src 'self' 'wasm-unsafe-eval'", PASS),
        ("script-src 'self' 'unsafe-eval'", ("passed", "passed", "failed")),
        (
            "default-src 'self'; script-src-elem https: 'unsafe-inline'",
            ("failed", "failed", "passed"),
        ),
        (
            "script-src https: 'unsafe-inline' 'unsafe-eval'; script-src-elem 'none'; script-src-attr 'none'",
            ("passed", "passed", "failed"),
        ),
        (
            "script-src 'self'; script-src-attr 'unsafe-inline'",
            ("passed", "failed", "passed"),
        ),
        (
            "script-src 'unsafe-inline'; script-src-elem 'none'; script-src-attr 'none'",
            PASS,
        ),
        ("script-src 'none'; script-src-elem 'unsafe-eval'", PASS),
        ("SCRIPT-SRC 'SELF'; script-src https: 'unsafe-inline' 'unsafe-eval'", PASS),
        ("script-src https: 'unsafe-inline' 'unsafe-eval'; script-src 'none'", FAIL),
        ("script-src 'none' https: 'unsafe-inline' 'unsafe-eval'", FAIL),
        ("script-src 'unsafe-inline' 'nonce-'", ("passed", "failed", "passed")),
        ("script-src 'unsafe-inline' 'nonce-a==='", ("passed", "failed", "passed")),
        ("script-src 'unsafe-inline' 'sha257-YWJj'", ("passed", "failed", "passed")),
        ("script-src 'unsafe-inline' 'NONCE-YWJj'", PASS),
        ("script-src https://*.test:8443/assets/", PASS),
        ("script-src https://*/assets/", ("inconclusive", "passed", "passed")),
        ("script-src https://*:8443", ("inconclusive", "passed", "passed")),
        ("script-src https://*:*", ("inconclusive", "passed", "passed")),
        ("script-src data:", ("inconclusive", "passed", "passed")),
        ("script-src blob:", ("inconclusive", "passed", "passed")),
        ("script-src ftp:", ("inconclusive", "passed", "passed")),
        ("script-src https: data:", ("failed", "passed", "passed")),
        (
            "script-src blob: 'unsafe-inline' 'unsafe-eval'",
            ("inconclusive", "failed", "failed"),
        ),
        ("script-src https://*?bad https://user@host.test 'broken", PASS),
        (
            "script-src \u017felf 'unsafe-inline' 'nonce-\u00e9'",
            FAIL,
        ),
        ("script-src\t'self'; unknown whatever", PASS),
        ("; ; script-src 'self' ; ;", PASS),
        (PERMISSIVE + "; sandbox", PASS),
        (PERMISSIVE + "; sandbox allow-forms ALLOW-SCRIPTS", FAIL),
        (PERMISSIVE + "; sandbox; sandbox allow-scripts", PASS),
        (PERMISSIVE + "; sandbox allow-scripts; sandbox", FAIL),
        (
            "script-src 'self' 'unsafe-eval'; require-trusted-types-for 'script'",
            ("passed", "passed", "inconclusive"),
        ),
        ("script-src 'self'; require-trusted-types-for 'script'", PASS),
        (
            "script-src 'self' 'trusted-types-eval'; require-trusted-types-for 'script'",
            ("passed", "passed", "inconclusive"),
        ),
        ("script-src 'self' 'trusted-types-eval'", PASS),
        (
            "frame-ancestors 'none'; require-trusted-types-for 'script'",
            ("failed", "failed", "inconclusive"),
        ),
        (PERMISSIVE + "; require-trusted-types-for 'invalid'", FAIL),
    ],
)
def test_script_permissions(policy, expected):
    assert_checks(response(policy), expected)


@pytest.mark.parametrize(
    "policies,expected",
    [
        ((PERMISSIVE, "script-src 'self'"), PASS),
        ((PERMISSIVE + ", script-src 'self'",), PASS),
        (("script-src 'self'", PERMISSIVE), PASS),
        ((PERMISSIVE, "frame-ancestors 'none'"), FAIL),
        (("script-src data:", "script-src 'self'"), PASS),
        (
            ("script-src data:", "script-src https:"),
            ("inconclusive", "passed", "passed"),
        ),
        (
            (
                "script-src https: 'unsafe-inline'; script-src-attr 'none'",
                "script-src https:; script-src-attr 'unsafe-inline'",
            ),
            ("failed", "passed", "passed"),
        ),
        (
            ("script-src https:; script-src-elem 'unsafe-inline'", PERMISSIVE),
            ("passed", "failed", "passed"),
        ),
        (
            (
                "script-src 'self' 'unsafe-eval'; require-trusted-types-for 'script'",
                "script-src 'none'",
            ),
            PASS,
        ),
        ((PERMISSIVE, "sandbox"), PASS),
    ],
)
def test_all_policies_must_permit_the_same_context(policies, expected):
    assert_checks(response(*policies), expected)


@pytest.mark.parametrize(
    "policy,expected",
    [
        ("script-src 'none' \u00e9", FAIL),
        ("default-src 'none' \u00e9", FAIL),
        (PERMISSIVE + "; sandbox \u00e9", FAIL),
        ("default-src 'self'; script-src 'none' \u00e9", PASS),
        ("script-src 'none' \u00e9; " + PERMISSIVE, FAIL),
        (PERMISSIVE + "; script-src 'none' \u00e9", FAIL),
        ("script-src 'none'; " + PERMISSIVE + " \u00e9", PASS),
        (
            "script-src 'none' \u00e9; script-src-elem 'self'",
            ("passed", "failed", "failed"),
        ),
        (
            "script-src 'self' 'unsafe-eval'; require-trusted-types-for 'script' \u00e9",
            ("passed", "passed", "failed"),
        ),
    ],
)
def test_non_ascii_values_discard_the_entire_directive(policy, expected):
    assert_checks(response(policy), expected)


@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("restriction", [None, "script-src 'self'", "sandbox"])
def test_trusted_types_requirements_apply_across_the_policy_set(
    combined, reverse, restriction
):
    policies = [
        "script-src 'self' 'trusted-types-eval'",
        "require-trusted-types-for 'script'",
    ]
    if reverse:
        policies.reverse()
    if restriction:
        policies.append(restriction)
    if combined:
        policies = [", ".join(policies)]
    expected = (
        PASS if restriction == "sandbox" else ("passed", "passed", "inconclusive")
    )
    assert_checks(response(*policies), expected)


@pytest.mark.parametrize(
    "policy",
    [
        "script-src 'self'; script-src-elem 'trusted-types-eval'",
        "script-src 'self'; script-src-attr 'trusted-types-eval'",
        "default-src 'self' 'trusted-types-eval'; script-src 'self'",
        "script-src 'self'; script-src 'self' 'trusted-types-eval'",
        "script-src 'self' 'trusted-types-eval' \u00e9; script-src 'self'",
    ],
)
def test_trusted_types_eval_interaction_uses_only_effective_eval_sources(policy):
    assert_checks(response(policy, "require-trusted-types-for 'script'"), PASS)


def test_report_only_eval_keyword_does_not_relax_enforced_restrictions():
    assert_checks(
        response(
            "script-src 'self'; require-trusted-types-for 'script'",
            extra={
                "content-security-policy-report-only": [
                    "script-src 'self' 'trusted-types-eval'"
                ]
            },
        ),
        PASS,
    )


def test_report_only_trusted_types_does_not_enable_trusted_types_eval():
    assert_checks(
        response(
            "script-src 'self' 'trusted-types-eval'",
            extra={
                "content-security-policy-report-only": [
                    "require-trusted-types-for 'script'"
                ]
            },
        ),
        PASS,
    )


@pytest.mark.parametrize("status", [101, 199, 204, 205, 301, 302, 303, 304, 307, 308])
def test_redirects_and_incomplete_representations(status):
    assert_checks(response(PERMISSIVE, status=status), ("skipped",) * 3)


@pytest.mark.parametrize("status", [200, 201, 400, 401, 404, 500])
def test_document_error_pages_are_evaluated(status):
    assert_checks(response(PERMISSIVE, status=status), FAIL)


@pytest.mark.parametrize(
    "media",
    [
        "application/json",
        "application/problem+json",
        "text/javascript",
        "application/javascript",
        "text/css",
        "text/plain",
        "image/png",
    ],
)
def test_non_documents_are_skipped(media):
    assert_checks(response(PERMISSIVE, content_type=media), ("skipped",) * 3)


@pytest.mark.parametrize("media", [None, "", "text/html; malformed", "image/svg+xml"])
def test_unknown_document_applicability(media):
    assert_checks(response(PERMISSIVE, content_type=media), ("inconclusive",) * 3)


def test_conflicting_content_types_are_inconclusive():
    assert_checks(
        response(
            PERMISSIVE,
            extra={
                "content-type": ["text/html", "application/json"],
            },
        ),
        ("inconclusive",) * 3,
    )


@pytest.mark.parametrize("fields", [(), ("",), (" \t",), (", , ;",)])
def test_absent_blank_and_empty_enforced_policies(fields):
    # A nonblank policy containing only ';' is still enforced and imposes no restrictions.
    expected = FAIL if fields == (", , ;",) else ("skipped",) * 3
    assert_checks(
        response(
            *fields,
            extra={
                "Content-Security-Policy-Report-Only": [PERMISSIVE],
            },
        ),
        expected,
    )


@pytest.mark.parametrize("count", [31, 32, 33])
def test_header_field_budget(count):
    expected = PASS if count <= 32 else ("inconclusive",) * 3
    assert_checks(response(*(["script-src 'self'"] * count)), expected)


@pytest.mark.parametrize("count", [31, 32, 33])
def test_policy_budget(count):
    expected = PASS if count <= 32 else ("inconclusive",) * 3
    assert_checks(response(", ".join(["script-src 'self'"] * count)), expected)


@pytest.mark.parametrize("count", [127, 128, 129])
@pytest.mark.parametrize(
    "name", ["script-src", "ignored", "invalid@name", "nonascii-\u00e9"]
)
def test_directive_budget_includes_duplicates_and_ignored_directives(count, name):
    policy = "script-src 'self';" + ";".join([name + " https:"] * (count - 1))
    assert_checks(response(policy), PASS if count <= 128 else ("inconclusive",) * 3)


@pytest.mark.parametrize("count", [255, 256, 257])
@pytest.mark.parametrize("name", ["script-src", "ignored", "invalid@name"])
def test_token_budget_applies_before_collection_even_to_ignored_tokens(count, name):
    policy = "script-src 'self';" + name + " " + " ".join(["'self'"] * count)
    assert_checks(response(policy), PASS if count <= 256 else ("inconclusive",) * 3)


@pytest.mark.parametrize("count", [255, 256, 257])
def test_non_ascii_values_count_toward_the_token_budget(count):
    policy = "script-src 'self'; sandbox " + " ".join(["\u00e9"] * count)
    assert_checks(response(policy), PASS if count <= 256 else ("inconclusive",) * 3)


@pytest.mark.parametrize("size", [65535, 65536, 65537])
def test_total_byte_budget(size):
    prefix = "script-src 'self'; report-uri https://synthetic.test/"
    policy = prefix + "a" * (size - len(prefix))
    assert_checks(response(policy), PASS if size <= 65536 else ("inconclusive",) * 3)


def test_byte_budget_is_utf8_and_applies_across_fields():
    assert_checks(
        response("script-src 'self'; ignored " + "\u00e9" * 32768),
        ("inconclusive",) * 3,
    )
    assert_checks(
        response(
            "script-src 'self'; ignored " + "a" * 40000,
            "script-src 'self'; ignored " + "b" * 40000,
        ),
        ("inconclusive",) * 3,
    )


def test_limit_never_certifies_a_restrictive_prefix():
    assert_checks(
        response("sandbox," + ",".join([PERMISSIVE] * 32)), ("inconclusive",) * 3
    )


def test_redaction_context_coverage_and_severity(caplog):
    policy = (
        "script-src https: 'unsafe-inline' 'unsafe-eval' https://synthetic-host-marker.test; "
        "report-uri https://synthetic-report-marker.test/; "
        "ignored 'nonce-synthetic-nonce-marker' 'sha256-synthetic-hash-marker'"
    )
    result = assert_checks(response(policy, "frame-ancestors 'none'"), FAIL)
    assert [finding.severity for finding in result.findings] == [
        "medium",
        "medium",
        "low",
    ]
    assert PLUGIN.manifest.id == "csp-policy"
    serialized = result.model_dump_json() + caplog.text
    for marker in (
        "synthetic-host-marker",
        "synthetic-report-marker",
        "synthetic-nonce-marker",
        "synthetic-hash-marker",
    ):
        assert marker not in serialized
    inline = result.findings[1].evidence
    assert inline["policy_count"] == 2
    assert [
        (item["context"], item["policy_index"]) for item in inline["observations"]
    ] == [
        ("inline-script", 1),
        ("inline-script", 2),
        ("script-attribute", 1),
        ("script-attribute", 2),
    ]
    assert json.loads(result.model_dump_json())["findings"][0]["evidence"][
        "observations"
    ][0] == {
        "policy_index": 1,
        "context": "network-script",
        "directive": "script-src",
        "condition": "https-scheme-source",
    }


def test_maximum_evidence_coverage_remains_bounded():
    result = assert_checks(response(*([PERMISSIVE] * 32)), FAIL)
    assert len(result.findings[1].evidence["observations"]) == 64


def test_nonblank_invalid_directives_do_not_create_phantom_restrictions():
    assert_checks(response("script_src 'none'; \u017fcript-src 'none'"), FAIL)

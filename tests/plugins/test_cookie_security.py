"""Conservative cookie checks and value-free findings."""

import logging

import pytest

from app.plugins.base import HttpObservation
from app.plugins.cookie_security import _parse, analyze

URL = "https://example.test/app"
SECRET = "synthetic-value-never-retained"


def findings(*cookies, url=URL):
    return analyze(
        HttpObservation(
            url=url, headers={"Set-Cookie": list(cookies)} if cookies else {}
        )
    ).findings


@pytest.mark.parametrize(
    "cookie",
    [
        f"theme={SECRET}",
        f"theme={SECRET}; SameSite=Lax",
        f"theme={SECRET}; SameSite=Strict",
        f"cross={SECRET}; SameSite=None; Secure",
        f"__Secure-session={SECRET}; Secure",
        f"__Host-session={SECRET}; Secure; Path=/",
        f"__Host-session={SECRET}; Secure; Path=/; Domain=",
        f"__secure-session={SECRET}; Secure",
        f"__host-session={SECRET}; Secure; Path=/",
        f"theme={SECRET}; SameSite=invalid; Future=ignored",
        f"__Host-session={SECRET}; Secure; Secure=false; Path=/",
        f'theme="{SECRET}"; SameSite=Lax',
        "theme=; SameSite=Lax",
    ],
)
def test_safe_or_uncovered_configurations_have_no_findings(cookie):
    assert not findings(cookie)


@pytest.mark.parametrize("same_site", ["None", "none", "nOnE", " None "])
def test_samesite_none_requires_secure(same_site):
    result = findings(f"cross={SECRET}; SaMeSiTe={same_site}")
    assert len(result) == 1
    assert result[0].evidence == {
        "url": URL,
        "header": "set-cookie",
        "cookie_name": "cross",
        "rule": "samesite-none-without-secure",
        "samesite": "none",
        "secure": False,
    }
    assert result[0].severity == "low"
    assert result[0].remediation


@pytest.mark.parametrize(
    "cookie,url,rule,flags",
    [
        (
            f"__Secure-session={SECRET}",
            URL,
            "secure-prefix",
            {"secure": False, "https": True},
        ),
        (
            f"__Secure-session={SECRET}; Secure",
            "http://example.test/",
            "secure-prefix",
            {"secure": True, "https": False},
        ),
        (
            f"__Host-session={SECRET}; Path=/",
            URL,
            "host-prefix",
            {
                "secure": False,
                "https": True,
                "domain_present": False,
                "root_path": True,
            },
        ),
        (
            f"__Host-session={SECRET}; Secure; Path=/",
            "http://example.test/",
            "host-prefix",
            {
                "secure": True,
                "https": False,
                "domain_present": False,
                "root_path": True,
            },
        ),
        (
            f"__Host-session={SECRET}; Secure; Path=/; Domain=example.test",
            URL,
            "host-prefix",
            {"secure": True, "https": True, "domain_present": True, "root_path": True},
        ),
        (
            f"__Host-session={SECRET}; Secure",
            URL,
            "host-prefix",
            {
                "secure": True,
                "https": True,
                "domain_present": False,
                "root_path": False,
            },
        ),
        (
            f"__Host-session={SECRET}; Secure; Path=/app",
            URL,
            "host-prefix",
            {
                "secure": True,
                "https": True,
                "domain_present": False,
                "root_path": False,
            },
        ),
        (
            f"__Host-session={SECRET}; Domain=example.test; Path=/app",
            "http://example.test/",
            "host-prefix",
            {
                "secure": False,
                "https": False,
                "domain_present": True,
                "root_path": False,
            },
        ),
    ],
)
def test_each_prefix_reports_one_finding_for_all_failed_requirements(
    cookie, url, rule, flags
):
    result = findings(cookie, url=url)
    assert len(result) == 1
    assert result[0].evidence == {
        "url": url,
        "header": "set-cookie",
        "cookie_name": cookie.partition("=")[0],
        "rule": rule,
        **flags,
    }
    assert result[0].severity == "low"
    assert result[0].remediation


@pytest.mark.parametrize(
    "name,attributes,rule",
    [
        ("__secure-session", "Secure", "secure-prefix"),
        ("__SECURE-session", "Secure", "secure-prefix"),
        ("__sEcUrE-session", "Secure", "secure-prefix"),
        ("__host-session", "Secure; Path=/", "host-prefix"),
        ("__HOST-session", "Secure; Path=/", "host-prefix"),
        ("__hOsT-session", "Secure; Path=/", "host-prefix"),
    ],
)
def test_prefix_matching_ignores_case_but_preserves_cookie_names(
    name, attributes, rule
):
    assert not findings(f"{name}={SECRET}; {attributes}")
    for cookie, url in [
        (f"{name}={SECRET}", URL),
        (f"{name}={SECRET}; {attributes}", "http://example.test/"),
    ]:
        result = findings(cookie, url=url)
        assert len(result) == 1
        assert result[0].evidence["rule"] == rule
        assert result[0].evidence["cookie_name"] == name
        assert repr(name) in result[0].description


def test_parser_retains_only_used_attributes_and_leaves_shared_headers_intact():
    field = (
        f"__Host-session={SECRET}; HttpOnly; Max-Age=3600; Partitioned; Future={SECRET}; "
        "Expires=Wed, 21 Oct 2037 07:28:00 GMT; Secure=unused; SameSite=Lax; Domain=; Path=/"
    )
    assert _parse(field) == (
        "__Host-session",
        {"secure": "", "samesite": "Lax", "domain": "", "path": "/"},
    )
    observation = HttpObservation(url=URL, headers={"Set-Cookie": [field]})
    assert not analyze(observation).findings
    assert observation.headers == {"set-cookie": [field]}


@pytest.mark.parametrize("character", ["a", "\u00e9"])
@pytest.mark.parametrize("length", [1024, 1025])
def test_secure_value_limit_counts_decoded_wire_bytes(character, length):
    field = f"cross={SECRET}; SameSite=None; Secure= \t{character * length}\t "
    parsed = _parse(field)
    assert parsed == (
        "cross",
        {"samesite": "None", **({"secure": ""} if length == 1024 else {})},
    )
    result = findings(field)
    assert [item.evidence["rule"] for item in result] == (
        [] if length == 1024 else ["samesite-none-without-secure"]
    )


@pytest.mark.parametrize("length", [1024, 1025])
@pytest.mark.parametrize(
    "name,attributes,duplicate,accepted_rules,ignored_rules",
    [
        ("theme", "SameSite=None", "SameSite", [], ["samesite-none-without-secure"]),
        ("__Host-session", "Secure; Path=/", "Path", ["host-prefix"], []),
        ("__Host-session", "Secure; Path=/; Domain=", "Domain", ["host-prefix"], []),
        ("cross", "SameSite=None; Secure", "Secure", [], []),
    ],
)
def test_only_retained_duplicate_values_replace_earlier_attributes(
    length, name, attributes, duplicate, accepted_rules, ignored_rules
):
    field = f"{name}={SECRET}; {attributes}; {duplicate}={'a' * length}"
    assert [item.evidence["rule"] for item in findings(field)] == (
        accepted_rules if length == 1024 else ignored_rules
    )


def test_oversized_duplicates_preserve_nonempty_domain_and_samesite_none():
    field = (
        f"__Host-session={SECRET}; SameSite=None; Domain=example.test; Path=/; "
        f"SameSite={'a' * 1025}; Domain={'a' * 1025}; Path={'a' * 1025}"
    )
    result = findings(field)
    assert [item.evidence["rule"] for item in result] == [
        "samesite-none-without-secure",
        "host-prefix",
    ]
    assert result[1].evidence["domain_present"] is True
    assert result[1].evidence["root_path"] is True


@pytest.mark.parametrize(
    "attribute,expected", [("Domain", []), ("Path", ["host-prefix"])]
)
def test_oversized_attributes_without_earlier_values_are_ignored(attribute, expected):
    attributes = "Secure; Path=/" if attribute == "Domain" else "Secure"
    field = f"__Host-session={SECRET}; {attributes}; {attribute}={'a' * 1025}"
    assert [item.evidence["rule"] for item in findings(field)] == expected


@pytest.mark.parametrize("attribute", ["Future", "Secure"])
def test_malformed_fields_are_rejected_even_with_ignored_attributes(attribute):
    field = f"cross={SECRET}; SameSite=None; {attribute}={'a' * 1025}\x00"
    assert _parse(field) is None
    assert not findings(field)


def test_independent_rules_and_repeated_cookie_names_are_preserved():
    result = findings(
        f"__Host-session={SECRET}; SameSite=None",
        f"__Host-session={SECRET}; Secure; Path=/",
        f"__Host-session={SECRET}; SameSite=None; Path=/app",
    )
    assert [item.evidence["rule"] for item in result] == [
        "samesite-none-without-secure",
        "host-prefix",
        "samesite-none-without-secure",
        "host-prefix",
    ]


@pytest.mark.parametrize(
    "name,attributes,expected",
    [
        ("theme", "SameSite=None; SameSite=Lax", []),
        ("theme", "SameSite=Lax; SameSite=None", ["samesite-none-without-secure"]),
        ("__Host-session", "Secure; Path=/app; PATH=/", []),
        ("__Host-session", "Secure; Path=/; Path=/app", ["host-prefix"]),
        ("__Host-session", "Secure; Path=/; Domain=example.test; DOMAIN=", []),
        (
            "__Host-session",
            "Secure; Path=/; Domain=; Domain=example.test",
            ["host-prefix"],
        ),
    ],
)
def test_last_valued_attribute_wins(name, attributes, expected):
    assert [
        item.evidence["rule"] for item in findings(f"{name}={SECRET}; {attributes}")
    ] == expected


def test_case_whitespace_quoted_values_and_expires_commas():
    result = findings(
        f'  cross = "{SECRET}" ; Expires=Wed, 21 Oct 2037 07:28:00 GMT; sAmEsItE = nOnE ; Future=ignored',
        f"__Host-session={SECRET}; sEcUrE; pAtH=/",
    )
    assert len(result) == 1
    assert result[0].evidence["cookie_name"] == "cross"


@pytest.mark.parametrize(
    "cookie",
    [
        "",
        "no-equals",
        f"={SECRET}",
        f"bad name={SECRET}; SameSite=None",
        f'theme="{SECRET}; SameSite=None',
        f'theme={SECRET}"; SameSite=None',
        f"theme={SECRET}, other=value; SameSite=None",
        f"theme={SECRET}\\invalid; SameSite=None",
        f"theme={SECRET}\r\n; SameSite=None",
        f"theme={SECRET}\x00; SameSite=None",
        "theme=non-ascii-\u00e9; SameSite=None",
    ],
)
def test_malformed_fields_are_skipped_without_losing_other_cookies(cookie):
    result = findings(cookie, f"cross={SECRET}; SameSite=None")
    assert len(result) == 1
    assert result[0].evidence["cookie_name"] == "cross"


def test_no_cookie_values_or_raw_attribute_values_in_findings(caplog):
    caplog.set_level(logging.DEBUG)
    observation = HttpObservation(
        url=URL,
        headers={
            "Set-Cookie": [
                f"__Host-session={SECRET}; SameSite=None; Domain={SECRET}; Path=/{SECRET}"
            ]
        },
    )
    response = analyze(observation)
    assert len(response.findings) == 2
    assert SECRET not in response.model_dump_json()
    assert SECRET not in caplog.text
    assert all(
        item.evidence["cookie_name"] == "__Host-session" for item in response.findings
    )


def test_no_cookies_produces_no_findings():
    assert findings() == ()

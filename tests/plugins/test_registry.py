"""Plugin contracts and registry behavior."""

import pytest
from pydantic import ValidationError

from app.plugins.base import (
    CheckOutcome,
    HttpObservation,
    Plugin,
    PluginFinding,
    PluginManifest,
    PluginResponse,
)
from app.plugins.http_security_headers import PLUGIN as SECURITY_HEADERS_PLUGIN
from app.plugins.registry import PluginRegistry, registry

URL = "http://demo-app:8080/"


@pytest.mark.parametrize(
    "changes",
    [
        {"rule_id": "invalid rule"},
        {"status": "unknown"},
        {"reason": ""},
        {"reason": " \t\n"},
        {"reason": "x" * 301},
    ],
)
def test_check_outcomes_reject_invalid_or_unexplained_results(changes):
    with pytest.raises(ValidationError):
        CheckOutcome(
            **{
                "rule_id": "rule",
                "status": "passed",
                "reason": "Protection recognized.",
                **changes,
            }
        )


def test_plugin_response_rejects_duplicate_checks():
    check = CheckOutcome(
        rule_id="rule", status="passed", reason="Protection recognized."
    )
    with pytest.raises(ValidationError, match="unique"):
        PluginResponse(findings=(), checks=(check, check))
    response = PluginResponse(findings=(), checks=(check,))
    assert PluginResponse.model_validate_json(response.model_dump_json()) == response


@pytest.mark.parametrize("value", [None, True, "200", 200.0, 99, 600])
def test_observation_requires_a_strict_http_status(value):
    with pytest.raises(ValidationError):
        HttpObservation(url=URL, status_code=value, headers={})


def test_observation_status_is_required():
    with pytest.raises(ValidationError):
        HttpObservation(url=URL, headers={})


@pytest.mark.parametrize(
    "fields,expected",
    [
        (["TEXT/HTML; charset=UTF-8"], "text/html"),
        (['text/html; charset="utf-8"', "text/html"], "text/html"),
        (["application/problem+json"], "application/problem+json"),
        ([], None),
        ([""], None),
        (["text/html,application/json"], None),
        (["text/html", "application/json"], None),
        (["text/html; garbage"], None),
        (["text/html\r\nSet-Cookie: synthetic-secret"], None),
        (["a" * 127 + "/" + "b" * 127], "a" * 127 + "/" + "b" * 127),
        (["a" * 128 + "/b"], None),
        (["a/" + "b" * 128], None),
        (['TEXT/HTML; Charset="utf-8"; version=1'], "text/html"),
        (["text/\u212a"], None),
        (["text/\u0130"], None),
        (["text/\u0131"], None),
        (["text/\u017f"], None),
    ],
)
def test_observation_normalizes_only_unambiguous_content_types(fields, expected):
    headers = {"Content-Type": fields} if fields else {}
    assert (
        HttpObservation(url=URL, status_code=200, headers=headers).media_type
        == expected
    )


def test_legacy_header_plugin_id_is_rejected():
    with pytest.raises(ValueError, match="unknown or inactive"):
        registry.select(["security-headers"])


def test_plugin_contract_round_trips_through_json(finding_payload):
    observation = HttpObservation(
        status_code=200, url=URL, headers={"Example": ["value"]}
    )
    restored_observation = HttpObservation.model_validate_json(
        observation.model_dump_json()
    )
    plugin_response = PluginResponse(findings=(PluginFinding(**finding_payload),))
    restored_response = PluginResponse.model_validate_json(
        plugin_response.model_dump_json()
    )
    assert restored_observation == observation
    assert restored_response == plugin_response


def test_observation_merges_case_insensitive_repeated_headers_in_order():
    observation = HttpObservation(
        status_code=200,
        url=URL,
        headers={
            "Set-Cookie": ["first=synthetic", "second=synthetic"],
            "set-cookie": ["third=synthetic"],
        },
    )
    assert observation.headers == {
        "set-cookie": ["first=synthetic", "second=synthetic", "third=synthetic"]
    }


@pytest.mark.parametrize(
    "headers",
    [
        [],
        {"Set-Cookie": "synthetic-secret"},
        {"Set-Cookie": [1]},
        {"Set-Cookie": []},
        {1: ["synthetic-secret"]},
    ],
)
def test_observation_rejects_invalid_headers_without_echoing_values(headers):
    with pytest.raises(ValidationError) as error:
        HttpObservation(status_code=200, url=URL, headers=headers)
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "x" * 301),
        ("severity", "x" * 31),
        ("evidence", {"invalid": object()}),
    ],
)
def test_finding_contract_rejects_unpersistable_values(field, value, finding_payload):
    values = finding_payload
    values[field] = value
    with pytest.raises(ValidationError):
        PluginFinding(**values)


@pytest.mark.parametrize("field", ["description", "remediation"])
@pytest.mark.parametrize("value", ["", " ", "\t\r\n", "\u00a0\u2003\u202f"])
def test_finding_contract_rejects_blank_text(field, value, finding_payload):
    values = finding_payload
    values[field] = value
    with pytest.raises(ValidationError) as error:
        PluginFinding(**values)
    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("field", ["description", "remediation"])
@pytest.mark.parametrize(
    "value",
    [
        "Useful text",
        "  Useful text  ",
        "\nSteps:\n\t1. Fix the header.\n",
        "\u2003Text\u00a0",
    ],
)
def test_finding_contract_preserves_meaningful_text(field, value, finding_payload):
    values = finding_payload
    values[field] = value
    finding = PluginFinding(**values)
    restored = PluginFinding.model_validate_json(finding.model_dump_json())
    assert getattr(finding, field) == getattr(restored, field) == value


def test_registry_is_ordered_validated_and_catalog_backed(make_plugin):
    def no_findings(observation):
        return PluginResponse(findings=())

    second = make_plugin("second", no_findings)
    local = PluginRegistry((SECURITY_HEADERS_PLUGIN, second))
    assert [item["id"] for item in local.catalog()] == [
        "http-security-headers",
        "second",
    ]
    assert [plugin.manifest.id for plugin in local.select(["second"])] == ["second"]
    assert [
        plugin.manifest.id
        for plugin in local.select(["second", "http-security-headers"])
    ] == ["second", "http-security-headers"]
    assert [
        plugin.manifest.id for plugin in registry.select(["http-security-headers"])
    ] == ["http-security-headers"]
    with pytest.raises(ValueError, match="unique"):
        PluginRegistry((second, second))


@pytest.mark.parametrize(
    "selection",
    [
        pytest.param(None, id="null"),
        pytest.param([], id="empty"),
        pytest.param("active", id="string"),
        pytest.param([None], id="null-id"),
        pytest.param(["missing"], id="unknown-id"),
        pytest.param(["active", "active"], id="duplicate-id"),
    ],
)
def test_registry_rejects_invalid_selections(selection, make_plugin):
    active = make_plugin("active", lambda observation: PluginResponse(findings=()))
    local = PluginRegistry((active,))
    with pytest.raises(ValueError):
        local.select(selection)


def test_registry_revalidates_manifests_at_construction():
    bypassed_manifest = PluginManifest.model_construct(
        id="Invalid ID",
        name="Invalid",
        description="Invalid plugin ID bypassing model validation",
    )
    plugin = Plugin(bypassed_manifest, lambda observation: PluginResponse(findings=()))

    with pytest.raises(ValueError, match="invalid manifest"):
        PluginRegistry((plugin,))


def test_registry_rejects_noncallable_analyzer():
    plugin = Plugin(SECURITY_HEADERS_PLUGIN.manifest, None)
    with pytest.raises(ValueError, match="must satisfy the plugin contract"):
        PluginRegistry((plugin,))

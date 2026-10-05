"""Plugin contracts and registry behavior."""

import pytest
from pydantic import ValidationError

from app.plugins.base import (
    HttpObservation,
    Plugin,
    PluginFinding,
    PluginManifest,
    PluginResponse,
)
from app.plugins.registry import PluginRegistry, registry
from app.plugins.security_headers import PLUGIN as SECURITY_HEADERS_PLUGIN

URL = "http://demo-target:8080/"


def test_plugin_contract_round_trips_through_json(finding_payload):
    observation = HttpObservation(url=URL, headers={"Example": ["value"]})
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
        HttpObservation(url=URL, headers=headers)
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
    assert [item["id"] for item in local.catalog()] == ["security-headers", "second"]
    assert [plugin.manifest.id for plugin in local.select(["second"])] == ["second"]
    assert [
        plugin.manifest.id for plugin in local.select(["second", "security-headers"])
    ] == ["second", "security-headers"]
    assert [plugin.manifest.id for plugin in registry.select(["security-headers"])] == [
        "security-headers"
    ]
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

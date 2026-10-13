"""Strict CSP evidence and real worker-to-API/report persistence."""

import json
from threading import Event

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.api.schemas import CspEvidenceData, EvidenceOut
from app.assessments.worker import AssessmentDispatcher
from app.persistence import models
from app.plugins.base import HttpObservation
from tests.sessions import FakeSession

PERMISSIVE = "script-src https: 'unsafe-inline' 'unsafe-eval'; frame-ancestors 'none'"


def evidence_data():
    return {
        "url": "http://demo-app:8080/",
        "header": "content-security-policy",
        "rule_id": "csp-script-sources",
        "status_code": 200,
        "media_type": "text/html",
        "policy_count": 2,
        "observations": [
            {
                "policy_index": 1,
                "context": "network-script",
                "directive": "script-src",
                "condition": "https-scheme-source",
            },
            {
                "policy_index": 2,
                "context": "network-script",
                "directive": None,
                "condition": "missing-directive",
            },
        ],
    }


def test_csp_evidence_round_trips_through_the_public_union():
    value = EvidenceOut(
        id="e", finding_id="f", kind="http-response", data=evidence_data()
    )
    assert isinstance(value.data, CspEvidenceData)
    assert EvidenceOut.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize(
    "change",
    [
        {"header": "set-cookie"},
        {"rule_id": "content-security-policy"},
        {"status_code": True},
        {"status_code": 600},
        {"status_code": 302},
        {"status_code": 204},
        {"media_type": None},
        {"media_type": "application/json"},
        {"policy_count": 0},
        {"policy_count": 33},
        {"policy_count": 3},
        {"raw": "synthetic-csp-evidence-secret"},
        {"observations": []},
        {"observations": [{}] * 65},
    ],
)
def test_invalid_evidence_is_rejected_without_echoing_input(change):
    with pytest.raises(ValidationError) as error:
        CspEvidenceData.model_validate({**evidence_data(), **change})
    assert "synthetic-csp-evidence-secret" not in str(error.value)


@pytest.mark.parametrize(
    "change",
    [
        {"context": "eval"},
        {"context": "synthetic-csp-evidence-secret"},
        {"directive": "script-src-attr"},
        {"directive": None},
        {"condition": "unsafe-eval"},
        {"condition": "missing-directive"},
        {"condition": "synthetic-csp-evidence-secret"},
        {"policy_index": 0},
        {"policy_index": True},
        {"policy_index": 3},
        {"raw": "synthetic-csp-evidence-secret"},
    ],
)
def test_observation_context_conditions_and_indexes_are_consistent(change):
    data = evidence_data()
    data["observations"][0].update(change)
    with pytest.raises(ValidationError) as error:
        CspEvidenceData.model_validate(data)
    assert "synthetic-csp-evidence-secret" not in str(error.value)


def test_coverage_is_complete_for_each_context_and_has_no_duplicates():
    data = evidence_data()
    for observations in (
        data["observations"][:1],
        data["observations"] + data["observations"][:1],
    ):
        with pytest.raises(ValidationError):
            CspEvidenceData.model_validate({**data, "observations": observations})
    inline = {
        **data,
        "rule_id": "csp-inline-scripts",
        "observations": [
            {
                **row,
                "context": context,
                "condition": "missing-directive"
                if row["directive"] is None
                else "unsafe-inline",
            }
            for context in ("inline-script", "script-attribute")
            for row in data["observations"]
        ],
    }
    CspEvidenceData.model_validate(inline)
    inline["observations"].pop()
    with pytest.raises(ValidationError, match="complete policy coverage"):
        CspEvidenceData.model_validate(inline)


@pytest.mark.parametrize(
    "plugins",
    [
        ["csp-policy"],
        ["csp-policy", "http-security-headers", "cookie-security"],
    ],
)
@pytest.mark.parametrize("nonce", [False, True])
def test_worker_persists_selected_csp_checks_and_safe_report_evidence(
    read_client, database, assessment_graph, monkeypatch, caplog, plugins, nonce
):
    graph = assessment_graph(plugins=plugins)
    calls = []
    policy = PERMISSIVE
    if nonce:
        policy += "; script-src-elem https: 'nonce-syntheticNonceMarker' 'sha256-syntheticHashMarker'"
    else:
        policy += "; ignored 'nonce-syntheticNonceMarker' 'sha256-syntheticHashMarker'"
    policy += "; report-uri https://syntheticReportMarker.test/"

    def fetch(self, url):
        url = url["url"]
        calls.append(url)
        return {
            "observation": HttpObservation(
                url=url,
                status_code=200,
                headers={
                    "Content-Type": ["text/html"],
                    "X-Content-Type-Options": ["nosniff"],
                    "Content-Security-Policy": [policy, "frame-ancestors 'none'"],
                },
            ),
            "redirects": [],
        }

    monkeypatch.setattr(FakeSession, "fetch", fetch)
    AssessmentDispatcher()._run(graph.assessment.id, Event())
    assert calls == [graph.assessment.url]
    base = f"/api/v1/assessments/{graph.assessment.id}"
    results = read_client.get(base + "/results").json()
    evidence = read_client.get(base + "/evidence").json()
    report_response = read_client.get(base + "/report")
    assert report_response.status_code == 200
    report = report_response.json()
    assert results["status"] == "completed"
    assert results["result"]["cleanup_verified"] is True
    assert [
        entry["id"] for entry in results["result"]["routes"][0]["plugins"]
    ] == plugins
    assert [
        entry["status"]
        for entry in results["result"]["routes"][0]["plugins"][0]["checks"]
    ] == [
        "failed",
        "failed",
        "failed",
    ]
    # A nonce on script elements does not suppress permissive script-attribute fallback.
    assert {row["plugin"] for row in results["findings"]} == {"csp-policy"}
    assert len(results["findings"]) == len(evidence["evidence"]) == 3
    if len(plugins) > 1:
        assert [
            entry["rule_id"]
            for entry in results["result"]["routes"][0]["plugins"][1]["checks"]
        ] == [
            "x-content-type-options",
            "content-security-policy",
            "framing-protection",
        ]
        assert all(
            entry["status"] == "passed"
            for entry in results["result"]["routes"][0]["plugins"][1]["checks"]
        )
    assert report["schema_version"] == 1
    assert report["evidence"] == evidence["evidence"]
    assert report["assessment"]["result"] == results["result"]
    for entry in evidence["evidence"]:
        CspEvidenceData.model_validate(entry["data"])
    serialized = json.dumps((results, evidence, report)) + caplog.text
    for marker in (
        "syntheticNonceMarker",
        "syntheticHashMarker",
        "syntheticReportMarker",
    ):
        assert marker not in serialized
    with database.SessionLocal() as db:
        assessment = db.get(models.Assessment, graph.assessment.id)
        assert assessment.result["finding_count"] == 3
        assert len(db.scalars(select(models.Finding)).all()) == 3


@pytest.mark.parametrize("suffix", ["/evidence", "/report"])
def test_corrupt_stored_csp_evidence_returns_a_generic_error(
    read_client, assessment_graph, evidence_row, caplog, suffix
):
    graph = assessment_graph()
    AssessmentDispatcher()._run(graph.assessment.id, Event())
    data = evidence_data()
    data["observations"][0]["condition"] = "synthetic-csp-evidence-secret"
    evidence_row(graph.assessment.id, data=data)
    response = read_client.get(f"/api/v1/assessments/{graph.assessment.id}" + suffix)
    assert response.status_code == 500
    assert response.json() == {"detail": "stored evidence is invalid"}
    assert "synthetic-csp-evidence-secret" not in response.text + caplog.text

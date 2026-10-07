from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from app.persistence import models
from tests.api.helpers import snapshot
from tests.header_evidence import header_evidence


def save_result(database, assessment_id, result, *, pending=False):
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, assessment_id)
        item.result = result
        item.cleanup_pending = pending
        db.commit()


def test_report_reads_the_authorized_project_once(
    read_client, database, assessment_graph
):
    graph = assessment_graph(status="completed")
    project_reads = []

    def record_select(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("SELECT") and "FROM projects" in statement:
            project_reads.append(statement)

    # The HTTP dependency opens a fresh session; fixture objects cannot cache its reads.
    event.listen(database.engine, "before_cursor_execute", record_select)
    try:
        response = read_client.get(f"/api/v1/assessments/{graph.assessment.id}/report")
    finally:
        event.remove(database.engine, "before_cursor_execute", record_select)

    assert response.status_code == 200
    assert response.json()["project"]["id"] == graph.project.id
    assert len(project_reads) == 1


def test_report_matches_existing_reads_and_is_ordered_read_only(
    read_client, database, assessment_graph, evidence_row, monkeypatch
):
    graph = assessment_graph(
        status="completed", plugins=["cookie-security", "http-security-headers"]
    )
    first_finding, _ = evidence_row(graph.assessment.id, identity="z-evidence")
    second_finding, _ = evidence_row(graph.assessment.id, identity="a-evidence")
    other = assessment_graph(status="completed")
    evidence_row(other.assessment.id, identity="other-evidence")
    result = {
        "sandbox_backend": "inmemory",
        "attempt": 1,
        "completed_at": models.now().isoformat(),
        "cleanup_verified": True,
        "cleanup_reason": None,
        "finding_count": 2,
        "response": {
            "status_code": 200,
            "media_type": "text/html",
            "raw": "synthetic-secret",
        },
        "plugins": [
            {"id": "cookie-security", "finding_count": 0},
            {
                "id": "http-security-headers",
                "finding_count": 2,
                "checks": [
                    {
                        "rule_id": "content-security-policy",
                        "status": "failed",
                        "reason": "Missing policy.",
                        "raw": "synthetic-secret",
                    }
                ],
                "raw": "synthetic-secret",
            },
        ],
        "raw": "synthetic-secret",
    }
    save_result(database, graph.assessment.id, result)
    from app.assessments.worker import dispatcher

    def unexpected(*args, **kwargs):
        raise AssertionError("report read attempted assessment work")

    monkeypatch.setattr(dispatcher, "submit", unexpected)
    monkeypatch.setattr(dispatcher, "cancel", unexpected)
    before = snapshot(database)
    path = f"/api/v1/assessments/{graph.assessment.id}"
    response = read_client.get(path + "/report")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    report = response.json()
    assert report["schema_version"] == 1
    assert datetime.fromisoformat(
        report["generated_at"]
    ).utcoffset() == timezone.utc.utcoffset(None)
    assert (
        report["project"]
        == read_client.get(f"/api/v1/projects/{graph.project.id}").json()
    )
    assert (
        report["target"] == read_client.get(f"/api/v1/targets/{graph.target.id}").json()
    )
    assessment = read_client.get(path).json()
    assert {k: v for k, v in report["assessment"].items() if k != "result"} == {
        k: v for k, v in assessment.items() if k != "result"
    }
    results = read_client.get(path + "/results").json()
    assert report["findings"] == sorted(results["findings"], key=lambda f: f["id"])
    assert {f["id"] for f in report["findings"]} == {first_finding, second_finding}
    assert report["evidence"] == read_client.get(path + "/evidence").json()["evidence"]
    assert "synthetic-secret" not in response.text
    assert report["assessment"]["plugins"] == [
        "cookie-security",
        "http-security-headers",
    ]
    assert "checks" not in report["assessment"]["result"]["plugins"][0]
    assert report["assessment"]["result"]["plugins"][1]["checks"][0] == {
        "rule_id": "content-security-policy",
        "status": "failed",
        "reason": "Missing policy.",
    }
    assert snapshot(database) == before


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_reports_preserve_absent_results(
    read_client, database, assessment_graph, status
):
    graph = assessment_graph(status=status)
    report = read_client.get(f"/api/v1/assessments/{graph.assessment.id}/report").json()
    assert report["assessment"]["status"] == status
    assert report["assessment"]["result"] is None
    assert report["findings"] == report["evidence"] == []


def test_reports_reflect_reconciliation_without_certifying_cleanup(
    read_client, database, assessment_graph
):
    graph = assessment_graph(status="failed")
    path = f"/api/v1/assessments/{graph.assessment.id}/report"
    result = {
        "error": "Execution failed",
        "cleanup_verified": False,
        "cleanup_reason": "Unknown creation outcome",
    }
    save_result(database, graph.assessment.id, result, pending=True)
    pending = read_client.get(path).json()
    assert pending["assessment"]["cleanup_pending"] is True
    assert pending["assessment"]["result"] == result
    save_result(
        database,
        graph.assessment.id,
        {**result, "cleanup_verified": True, "cleanup_reason": None},
    )
    reconciled = read_client.get(path).json()
    assert reconciled["assessment"]["status"] == "failed"
    assert reconciled["assessment"]["cleanup_pending"] is False
    assert reconciled["assessment"]["result"]["cleanup_verified"] is True
    assert reconciled["generated_at"] > pending["generated_at"]


@pytest.mark.parametrize("status", ["queued", "running", "cancelling", "recovering"])
def test_unfinished_reports_are_rejected_after_authorization(
    read_client, assessment_graph, status
):
    graph = assessment_graph(status=status)
    assert (
        read_client.get(f"/api/v1/assessments/{graph.assessment.id}/report").status_code
        == 409
    )
    denied = assessment_graph(status=status, owner="other-operator")
    assert (
        read_client.get(
            f"/api/v1/assessments/{denied.assessment.id}/report"
        ).status_code
        == 403
    )


def test_unknown_and_unauthorized_reports(read_client, assessment_graph):
    assert read_client.get("/api/v1/assessments/missing/report").status_code == 404
    graph = assessment_graph(status="completed", owner="other-operator")
    assert (
        read_client.get(f"/api/v1/assessments/{graph.assessment.id}/report").status_code
        == 403
    )


@pytest.mark.parametrize(
    "completed_at",
    [
        "2026-10-07T12:00:30Z",
        "2026-10-07T12:00:30+00:00",
        "2026-10-07T12:00:30.123456+02:30",
        "2026-10-07T12:00:30-05:30",
        "2026-10-07T12:00:30.1Z",
    ],
)
def test_report_preserves_supported_completion_timestamps(
    read_client, database, assessment_graph, completed_at
):
    graph = assessment_graph(status="completed")
    save_result(database, graph.assessment.id, {"completed_at": completed_at})
    path = f"/api/v1/assessments/{graph.assessment.id}"
    response = read_client.get(path + "/report")
    assert response.status_code == 200
    assert (
        response.json()["assessment"]["result"]
        == read_client.get(path + "/results").json()["result"]
        == {"completed_at": completed_at}
    )


@pytest.mark.parametrize("duplicate", [False, True])
def test_report_requires_unique_checks_and_preserves_their_order(
    read_client, database, assessment_graph, duplicate
):
    graph = assessment_graph(status="completed")
    checks = [
        {"rule_id": "second-rule", "status": "passed", "reason": "Accepted."},
        {
            "rule_id": "second-rule" if duplicate else "first-rule",
            "status": "skipped",
            "reason": "Not applicable.",
        },
    ]
    save_result(
        database,
        graph.assessment.id,
        {
            "plugins": [
                {"id": "http-security-headers", "finding_count": 0, "checks": checks}
            ]
        },
    )
    response = read_client.get(f"/api/v1/assessments/{graph.assessment.id}/report")
    if duplicate:
        assert response.status_code == 500
        assert response.json() == {"detail": "stored report data is invalid"}
    else:
        assert response.status_code == 200
        assert response.json()["assessment"]["result"]["plugins"][0]["checks"] == checks


@pytest.mark.parametrize(
    "result",
    [
        {"attempt": "synthetic-report-secret"},
        {"attempt": True},
        {"attempt": 0},
        {"cleanup_verified": "synthetic-report-secret"},
        {"cleanup_verified": None},
        {"completed_at": "synthetic-report-secret"},
        {"completed_at": "2026-10-07T12:00:00"},
        {"completed_at": "20261007T120000+0000"},
        {"completed_at": "2026-10-07T12:00:00+00:00:01"},
        {"completed_at": "2026-10-07T12:00:00+00:60"},
        {"completed_at": "2026-10-07 12:00:00+00:00"},
        {"completed_at": "2026-10-07T12:00:00,123456+00:00"},
        {"completed_at": "2026-02-30T12:00:00Z"},
        {"response": {"status_code": 600, "media_type": None}},
        {
            "response": {
                "status_code": 200,
                "media_type": "text/html;synthetic-report-secret",
            }
        },
        {"plugins": [{"id": "example", "finding_count": 0, "checks": None}]},
        {
            "plugins": [
                {
                    "id": "example",
                    "finding_count": 0,
                    "checks": [
                        {
                            "rule_id": "rule",
                            "status": "synthetic-report-secret",
                            "reason": "A reason",
                        }
                    ],
                }
            ]
        },
    ],
)
def test_invalid_result_fails_without_partial_export_or_diagnostics(
    read_client, database, assessment_graph, evidence_row, caplog, result
):
    graph = assessment_graph(status="completed")
    evidence_row(graph.assessment.id)
    save_result(database, graph.assessment.id, result)
    response = read_client.get(f"/api/v1/assessments/{graph.assessment.id}/report")
    assert response.status_code == 500
    assert response.json() == {"detail": "stored report data is invalid"}
    assert graph.assessment.id in caplog.text
    assert "synthetic-report-secret" not in response.text + caplog.text


def test_invalid_evidence_uses_existing_fail_closed_read(
    read_client, assessment_graph, evidence_row, caplog
):
    graph = assessment_graph(status="completed")
    evidence_row(graph.assessment.id, identity="a-valid")
    evidence_row(
        graph.assessment.id,
        identity="z-invalid",
        data={**header_evidence(), "raw": "synthetic-evidence-secret"},
    )
    response = read_client.get(f"/api/v1/assessments/{graph.assessment.id}/report")
    assert response.status_code == 500
    assert response.json() == {"detail": "stored evidence is invalid"}
    assert "synthetic-evidence-secret" not in response.text + caplog.text

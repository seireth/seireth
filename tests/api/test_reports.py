"""Reports read current persisted results without rerunning or inventing data."""

from copy import deepcopy

import pytest
from sqlalchemy import select

from app.assessments.worker import AssessmentDispatcher
from app.assessments.workflows import refresh_result
from app.persistence import models
from tests.api.helpers import snapshot


@pytest.fixture
def completed(database, assessment_graph):
    graph = assessment_graph()
    AssessmentDispatcher()._run(graph.assessment.id, __import__("threading").Event())
    with database.SessionLocal() as db:
        assert db.get(models.Assessment, graph.assessment.id).status == "completed"
    return graph


def mutate_result(database, graph, change):
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, graph.assessment.id)
        result = deepcopy(item.result)
        change(result)
        item.result = result
        db.commit()


def test_report_matches_reads_and_does_not_write(read_client, database, completed):
    base = f"/api/v1/assessments/{completed.assessment.id}"
    before = snapshot(database)
    response = read_client.get(base + "/report")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["schema_version"] == 1
    assert report["assessment"] == read_client.get(base).json()
    assert report["findings"] == read_client.get(base + "/results").json()["findings"]
    assert report["evidence"] == read_client.get(base + "/evidence").json()["evidence"]
    assert len(report["findings"]) == len(report["evidence"]) == 3
    assert all(
        finding["route_result_id"] == report["assessment"]["result"]["routes"][0]["id"]
        for finding in report["findings"]
    )
    assert (
        "response" not in report["assessment"]["result"]
        and "plugins" not in report["assessment"]["result"]
    )
    assert response.headers["cache-control"] == "no-store"
    assert snapshot(database) == before


def test_report_uses_frozen_target_after_registration_changes(
    read_client, database, completed
):
    with database.SessionLocal() as db:
        target = db.get(models.Target, completed.target.id)
        target.name, target.url, target.image = (
            "Changed",
            "http://different.test/",
            "other:local",
        )
        db.commit()
    report = read_client.get(
        f"/api/v1/assessments/{completed.assessment.id}/report"
    ).json()
    assert report["target"] == completed.assessment.plan_snapshot["target"]


@pytest.mark.parametrize("status", ["running", "failed"])
def test_corrupt_journal_preserves_provenance_and_failure(
    read_client, database, completed, status
):
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, completed.assessment.id)
        attempt = db.scalar(
            select(models.Attempt).where(models.Attempt.assessment_id == item.id)
        )
        item.status, item.cleanup_pending = status, True
        item.result = {
            **item.result,
            "error": "original execution failure",
            "execution_outcome": "failed",
        }
        attempt.operation_journal = {}
        execution = deepcopy(attempt.execution_metadata)
        db.commit()
    dispatcher = AssessmentDispatcher()
    dispatcher.recover(include_failed_cleanup=True)
    response = read_client.get(f"/api/v1/assessments/{completed.assessment.id}/report")
    assert response.status_code == 200, response.text
    report = response.json()
    result = report["assessment"]["result"]
    assert result["execution"] == execution
    assert result["error"] == "original execution failure"
    assert (
        result["cleanup_verified"] is False and report["assessment"]["cleanup_pending"]
    )
    assert result["verdict"]["status"] == "blocked"
    assert report["findings"] == report["evidence"] == []


@pytest.mark.parametrize("status", ["queued", "running", "cancelling", "recovering"])
def test_unfinished_reports_are_rejected(
    read_client, database, assessment_graph, status
):
    graph = assessment_graph(status=status)
    assert (
        read_client.get(f"/api/v1/assessments/{graph.assessment.id}/report").status_code
        == 409
    )


def test_queued_cancellation_reports_without_an_attempt(
    read_client, database, assessment_graph
):
    graph = assessment_graph()
    base = f"/api/v1/assessments/{graph.assessment.id}"
    assert read_client.post(base + "/cancel").status_code == 200
    report = read_client.get(base + "/report").json()
    result = report["assessment"]["result"]
    assert result["execution_outcome"] == "not_started" and "attempt" not in result
    assert result["cleanup_verified"] and result["verdict"]["status"] == "blocked"
    assert result["routes"][0]["status"] == "unattempted"


def test_preflight_version_mismatch_is_reported_without_execution(
    read_client, database, assessment_graph
):
    graph = assessment_graph()
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, graph.assessment.id)
        plan = deepcopy(item.plan_snapshot)
        plan["plugins"][0]["version"] = "9.0.0"
        item.plan_snapshot = plan
        db.commit()
    AssessmentDispatcher()._run(graph.assessment.id, __import__("threading").Event())
    response = read_client.get(f"/api/v1/assessments/{graph.assessment.id}/report")
    assert response.status_code == 200, response.text
    result = response.json()["assessment"]["result"]
    assert result["execution_outcome"] == "not_started"
    assert result["error"] == "installed plugin versions differ from the queued plan"
    assert result["cleanup_verified"] and "attempt" not in result


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-10-07T12:00:30Z",
        "2026-10-07T12:00:30.123456+02:30",
        "2026-10-07T12:00:30-05:30",
    ],
)
def test_supported_completion_timestamps_are_preserved(
    read_client, database, completed, timestamp
):
    mutate_result(
        database, completed, lambda result: result.update(completed_at=timestamp)
    )
    report = read_client.get(
        f"/api/v1/assessments/{completed.assessment.id}/report"
    ).json()
    assert report["assessment"]["result"]["completed_at"] == timestamp


@pytest.mark.parametrize(
    "field,value",
    [
        ("completed_at", "secret-invalid-time"),
        ("cleanup_verified", "true"),
        ("execution_outcome", "old"),
        ("response", {}),
        ("plugins", []),
        ("sandbox_backend", "unsupported"),
    ],
)
def test_current_result_schema_rejects_unsupported_fields(
    read_client, database, completed, field, value, caplog
):
    mutate_result(database, completed, lambda result: result.update({field: value}))
    response = read_client.get(f"/api/v1/assessments/{completed.assessment.id}/report")
    assert response.status_code == 500
    assert response.json() == {"detail": "stored report data is invalid"}
    assert "secret-invalid-time" not in caplog.text


def test_duplicate_checks_fail_report_validation(read_client, database, completed):
    def change(result):
        checks = result["routes"][0]["plugins"][0]["checks"]
        checks.append(checks[0])

    mutate_result(database, completed, change)
    assert (
        read_client.get(
            f"/api/v1/assessments/{completed.assessment.id}/report"
        ).status_code
        == 500
    )


@pytest.mark.parametrize("field", ["cleanup_verified", "finding_count"])
def test_terminal_report_requires_current_outcome_fields(
    read_client, database, completed, field
):
    mutate_result(database, completed, lambda result: result.pop(field))
    assert (
        read_client.get(
            f"/api/v1/assessments/{completed.assessment.id}/report"
        ).status_code
        == 500
    )


@pytest.mark.parametrize("version", [None, 2, 3])
def test_report_requires_current_format(read_client, completed, version):
    from pydantic import ValidationError

    from app.api.schemas import AssessmentReportOut

    report = read_client.get(
        f"/api/v1/assessments/{completed.assessment.id}/report"
    ).json()
    if version is None:
        report.pop("schema_version")
    else:
        report["schema_version"] = version
    with pytest.raises(ValidationError):
        AssessmentReportOut.model_validate(report)


def test_cleanup_reconciliation_cannot_turn_failure_into_pass(
    read_client, database, completed
):
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, completed.assessment.id)
        attempt = db.scalar(
            select(models.Attempt).where(models.Attempt.assessment_id == item.id)
        )
        item.status, item.cleanup_pending = "failed", True
        item.result = {
            **item.result,
            "execution_outcome": "failed",
            "error": "execution failed",
        }
        attempt.cleanup_verified = False
        refresh_result(db, item, attempt)
        db.commit()
    dispatcher = AssessmentDispatcher()
    dispatcher.recover(include_failed_cleanup=True)
    report = read_client.get(
        f"/api/v1/assessments/{completed.assessment.id}/report"
    ).json()
    assert report["assessment"]["status"] == "failed"
    assert report["assessment"]["result"]["cleanup_verified"]
    assert report["assessment"]["result"]["verdict"]["status"] == "blocked"


def test_unknown_and_unauthorized_reports(read_client, database, assessment_graph):
    assert read_client.get("/api/v1/assessments/missing/report").status_code == 404
    graph = assessment_graph(owner="another-operator")
    assert (
        read_client.get(f"/api/v1/assessments/{graph.assessment.id}/report").status_code
        == 403
    )

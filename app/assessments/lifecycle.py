"""Assessment transitions, audit events, and results within caller transactions."""

from sqlalchemy import select

from ..persistence import models

ALLOWED = {
    "queued": {"running", "cancelled", "failed"},
    "running": {"cancelling", "recovering", "completed", "cancelled", "failed"},
    "recovering": {"queued", "cancelling", "cancelled", "failed"},
    "cancelling": {"cancelled", "failed"},
}


def latest_attempt(db, assessment_id):
    return db.scalar(
        select(models.Attempt)
        .where(models.Attempt.assessment_id == assessment_id)
        .order_by(models.Attempt.number.desc())
        .limit(1)
    )


def transition(db, assessment, status, details=None):
    if status not in ALLOWED.get(assessment.status, set()):
        raise ValueError(
            f"Invalid assessment transition: {assessment.status} -> {status}"
        )
    assessment.status = models.AssessmentStatus(status)
    audit(db, assessment.project_id, f"assessment.{status}", assessment.id, details)


def audit(db, project_id, action, resource_id, details=None):
    """Add an audit record to the caller's transaction."""
    db.add(
        models.AuditEvent(
            project_id=project_id,
            action=action,
            resource_id=resource_id,
            details=details or {},
        )
    )


def attempt_result(attempt):
    """Project persisted execution identity for finalization and failed recovery."""
    result = {
        "sandbox_backend": attempt.backend,
        "attempt": attempt.number,
    }
    if attempt.finished_at is not None:
        result["completed_at"] = attempt.finished_at.isoformat()
    result["execution"] = {
        key: attempt.execution_metadata[key]
        for key in ("started_at", "deadline_at", "target", "plugins")
    }
    return result


def finding_record(assessment_id, plugin, finding, *, route_result_id):
    """Build the normalized finding/evidence record for its originating route."""
    return models.Finding(
        assessment_id=assessment_id,
        route_result_id=route_result_id,
        plugin=plugin,
        **{
            key: finding[key]
            for key in ("title", "severity", "description", "remediation")
        },
        evidence=[models.Evidence(kind="http-response", data=finding["evidence"])],
    )


def finish(db, assessment, attempt, outcome):
    attempt.finished_at = models.now()
    attempt.cleanup_verified = outcome.cleanup_verified
    attempt.error = outcome.error
    assessment.cleanup_pending = not outcome.cleanup_verified
    result = {
        **attempt_result(attempt),
        "cleanup_verified": outcome.cleanup_verified,
        "cleanup_reason": outcome.cleanup_reason,
    }
    execution_status = outcome.execution_status or outcome.status
    result["execution_outcome"] = (
        "interrupted" if execution_status == "recovering" else execution_status
    )
    if outcome.error:
        result["error"] = outcome.error
    if outcome.error_kind:
        result["error_kind"] = outcome.error_kind
    if outcome.failed_plugin:
        result["failed_plugin"] = outcome.failed_plugin
    assessment.result = result
    transition(db, assessment, outcome.status, {"attempt": attempt.number})

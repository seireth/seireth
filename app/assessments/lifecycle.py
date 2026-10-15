"""Assessment transitions, audit events, and results within caller transactions."""

from sqlalchemy import select

from ..persistence import models
from .results import AssessmentResult

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


def terminal_result(
    *,
    execution_outcome,
    cleanup_verified,
    attempt=None,
    cleanup_reason=None,
    error=None,
    error_kind=None,
    failed_plugin=None,
    previous=None,
):
    """Build one validated terminal shape before route/comparison projection."""
    result = {
        "routes": [],
        "finding_count": 0,
        "coverage": {"complete": False},
        "verdict": {
            "policy": "strict-v1",
            "status": "blocked",
            "reasons": [error or "execution did not complete"],
        },
        "comparison": {"status": "not_requested"},
        "partial": False,
        **(previous or {}),
        "completed_at": (
            attempt.finished_at if attempt and attempt.finished_at else models.now()
        ).isoformat(),
        "execution_outcome": "interrupted"
        if execution_outcome == "recovering"
        else execution_outcome,
        "cleanup_verified": cleanup_verified,
        "cleanup_reason": cleanup_reason,
    }
    if attempt:
        result.update(
            sandbox_backend=attempt.backend,
            attempt=attempt.number,
            execution={
                key: attempt.execution_metadata[key]
                for key in ("started_at", "deadline_at", "target", "plugins")
            },
        )
    for key, value in (
        ("error", error),
        ("error_kind", error_kind),
        ("failed_plugin", failed_plugin),
    ):
        if value is not None:
            result[key] = value
    return AssessmentResult.model_validate(result).model_dump(
        mode="json", exclude_unset=True
    )


def finish(db, assessment, attempt, outcome):
    attempt.finished_at = models.now()
    attempt.cleanup_verified = outcome.cleanup_verified
    attempt.error = outcome.error
    assessment.cleanup_pending = not outcome.cleanup_verified
    assessment.result = terminal_result(
        attempt=attempt,
        execution_outcome=outcome.execution_status or outcome.status,
        cleanup_verified=outcome.cleanup_verified,
        cleanup_reason=outcome.cleanup_reason,
        error=outcome.error,
        error_kind=outcome.error_kind,
        failed_plugin=outcome.failed_plugin,
    )
    transition(db, assessment, outcome.status, {"attempt": attempt.number})

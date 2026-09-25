"""Single transaction boundary for assessment transitions and terminal results."""

from . import models

ALLOWED = {
    "queued": {"running", "cancelled", "failed"},
    "running": {"cancelling", "recovering", "completed", "cancelled", "failed"},
    "recovering": {"queued", "cancelling", "cancelled", "failed"},
    "cancelling": {"cancelled", "failed"},
}


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


def finish(db, assessment, attempt, outcome):
    attempt.finished_at = models.now()
    attempt.cleanup_verified = outcome.cleanup_verified
    attempt.error = outcome.error
    assessment.cleanup_pending = not outcome.cleanup_verified
    result = {
        "sandbox_backend": attempt.backend,
        "cleanup_verified": outcome.cleanup_verified,
        "cleanup_reason": outcome.cleanup_reason,
        "completed_at": attempt.finished_at.isoformat(),
        "attempt": attempt.number,
    }
    if outcome.error:
        result["error"] = outcome.error
    if outcome.status == "completed":
        result["plugins"] = [
            {"id": item.plugin_id, "finding_count": len(item.findings)}
            for item in outcome.plugin_results
        ]
        result["finding_count"] = sum(
            len(item.findings) for item in outcome.plugin_results
        )
        for item in outcome.plugin_results:
            for finding in item.findings:
                db.add(
                    models.Finding(
                        assessment_id=assessment.id,
                        plugin=item.plugin_id,
                        title=finding.title,
                        severity=finding.severity,
                        description=finding.description,
                        remediation=finding.remediation,
                    )
                )
                db.add(
                    models.Evidence(
                        assessment_id=assessment.id,
                        kind="http-response",
                        data=finding.evidence,
                    )
                )
    assessment.result = result
    transition(db, assessment, outcome.status, {"attempt": attempt.number})

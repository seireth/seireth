"""Lifecycle guards and audit records without a database connection."""

from unittest.mock import Mock

import pytest

from app.assessments.lifecycle import transition
from app.persistence import models


@pytest.mark.parametrize(
    "before,after",
    [
        ("queued", "completed"),
        ("queued", "queued"),
        ("running", "queued"),
        ("recovering", "completed"),
        ("cancelling", "running"),
        ("completed", "running"),
        ("failed", "running"),
        ("cancelled", "running"),
    ],
)
def test_forbidden_transition_changes_neither_state_nor_audit(before, after):
    assessment = models.Assessment(
        id="assessment-1", project_id="project-1", status=before
    )
    db = Mock(spec=["add"])

    with pytest.raises(
        ValueError, match=f"Invalid assessment transition: {before} -> {after}"
    ):
        transition(db, assessment, after)

    assert assessment.status == before
    db.add.assert_not_called()


def test_allowed_transition_records_audit_in_callers_transaction():
    assessment = models.Assessment(
        id="assessment-1", project_id="project-1", status="queued"
    )
    db = Mock(spec=["add"])

    transition(db, assessment, "running", {"attempt": 1})

    assert assessment.status == models.AssessmentStatus.running
    db.add.assert_called_once()
    event = db.add.call_args.args[0]
    assert isinstance(event, models.AuditEvent)
    assert event.project_id == "project-1"
    assert event.resource_id == "assessment-1"
    assert event.action == "assessment.running"
    assert event.details == {"attempt": 1}

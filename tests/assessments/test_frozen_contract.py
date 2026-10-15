"""Only complete, current plans are accepted at execution and report boundaries."""

from copy import deepcopy
from threading import Event

import pytest
from pydantic import ValidationError

from app.assessments.plans import FrozenPlan, read_snapshot, verify_snapshot
from app.assessments.worker import AssessmentDispatcher
from app.persistence import models
from tests.sessions import frozen_plan


@pytest.mark.parametrize(
    "field",
    [
        "runner_limits",
        "cleanup_seconds",
        "control_endpoints",
        "ca",
        "network",
        "baseline",
    ],
)
def test_missing_frozen_fields_are_not_defaulted(mock_images, field):
    plan = frozen_plan()
    del plan[field]
    with pytest.raises(ValidationError):
        FrozenPlan.model_validate(plan)


@pytest.mark.parametrize(
    "path",
    [
        ("expected", "final_url"),
        ("request", "follow_redirects"),
        ("analysis", "expected_cookies"),
    ],
)
def test_nested_frozen_configuration_must_be_complete(mock_images, path):
    plan = frozen_plan()
    del plan["routes"][0][path[0]][path[1]]
    with pytest.raises(ValidationError):
        FrozenPlan.model_validate(plan)


def test_mutable_image_reference_is_not_an_execution_identity(mock_images):
    plan = frozen_plan()
    plan["images"]["target"] = "application:latest"
    with pytest.raises(ValidationError):
        FrozenPlan.model_validate(plan)


def test_invalid_stored_plan_fails_without_execution(
    database, assessment_graph, monkeypatch
):
    from app.assessments import worker

    graph = assessment_graph()
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, graph.assessment.id)
        plan = deepcopy(item.plan_snapshot)
        del plan["routes"]
        item.plan_snapshot = plan
        db.commit()
    monkeypatch.setattr(
        worker,
        "sandbox_for",
        lambda *a, **kw: pytest.fail("invalid plan cannot execute"),
    )
    AssessmentDispatcher()._run(graph.assessment.id, Event())
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, graph.assessment.id)
        assert item.status == "failed" and not item.cleanup_pending
        assert item.result["execution_outcome"] == "not_started"
        assert item.result["verdict"]["status"] == "blocked"


@pytest.mark.parametrize(
    "field,value",
    [
        ("timeout_seconds", "15.0"),
        ("timeout_seconds", True),
        ("timeout_seconds", float("nan")),
        ("cleanup_seconds", "60"),
        ("version", True),
    ],
)
def test_stored_plan_rejects_coercion(mock_images, field, value):
    plan = frozen_plan()
    plan[field] = value
    with pytest.raises(ValidationError):
        read_snapshot(plan)


def test_verified_snapshot_is_canonical_and_independent(mock_images):
    plan = frozen_plan()
    canonical = verify_snapshot(plan)
    assert canonical == plan and canonical is not plan
    canonical["routes"][0]["analysis"]["expected_cookies"].append("session")
    assert plan["routes"][0]["analysis"]["expected_cookies"] == []

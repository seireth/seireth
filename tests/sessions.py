"""Test doubles and complete records for the current execution contract."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.assessments.bundle import new_bundle_journal
from app.assessments.plans import RoutePlan, freeze_plan
from app.assessments.sandbox import CleanupOutcome
from app.core.identity import ACTOR
from app.persistence import models
from app.plugins.base import HttpObservation


def frozen_plan(*, target=None, plugins=None, url=None, timeout=60):
    target = target or SimpleNamespace(
        id="target",
        project_id="project",
        name="fixture",
        kind="docker",
        image="seireth/demo-app:local",
        url="http://demo-app:8080/",
        launch_profile=None,
        network_profile=None,
        trust_profile=None,
    )
    project = SimpleNamespace(id=target.project_id, owner_actor=ACTOR)
    return freeze_plan(
        project,
        target,
        [
            RoutePlan(
                key="response",
                url=url or target.url,
                plugins=plugins or ["http-security-headers"],
            )
        ],
        timeout_seconds=timeout,
    )


def execution_metadata(plan):
    start = models.now()
    return {
        "started_at": start.isoformat(),
        "deadline_at": (start + timedelta(seconds=plan["timeout_seconds"])).isoformat(),
        "target": plan["target"],
        "plugins": plan["plugins"],
    }


def attempt_record(*, plan=None, **values):
    plan = plan or frozen_plan()
    values.setdefault("id", str(uuid4()))
    values.setdefault("backend", "docker")
    values.setdefault("operation_journal", new_bundle_journal(plan, values["id"]))
    values.setdefault("execution_metadata", execution_metadata(plan))
    return models.Attempt(**values)


def completed_route(db, assessment):
    """Create explicit, current provenance for hand-built evidence fixtures."""
    from sqlalchemy import select

    attempt = db.scalar(
        select(models.Attempt).where(models.Attempt.assessment_id == assessment.id)
    )
    if attempt is None:
        attempt = attempt_record(
            plan=assessment.plan_snapshot,
            assessment_id=assessment.id,
            number=1,
            cleanup_verified=True,
            finished_at=models.now(),
        )
        db.add(attempt)
        db.flush()
    row = db.scalar(
        select(models.RouteResult).where(models.RouteResult.attempt_id == attempt.id)
    )
    if row is None:
        row = models.RouteResult(
            assessment_id=assessment.id,
            attempt_id=attempt.id,
            route_key="response",
            status="completed",
            data={"status": "completed", "plugins": []},
        )
        db.add(row)
        db.flush()
    return row


class FakeSession:
    def __init__(self, snapshot, *, context=None, persist_journal):
        self.snapshot = snapshot
        self.context = context
        self.persist_journal = persist_journal

    def prepare(self):
        pass

    def fetch(self, route):
        self.context.check()
        return {
            "observation": HttpObservation(
                url=route["url"],
                status_code=200,
                headers={"content-type": ["text/html"]},
            ),
            "redirects": [],
        }

    def cleanup(self):
        return CleanupOutcome(True)


def fake_factory(attempt, *, snapshot, persist_journal, context=None):
    return FakeSession(snapshot, context=context, persist_journal=persist_journal)

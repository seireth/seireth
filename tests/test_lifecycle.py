"""Regression tests through the real PostgreSQL-backed dispatcher."""

from datetime import timedelta
from threading import Event, Thread
from time import monotonic, sleep

import pytest
from sqlalchemy import select, text

from app import models
from app.config import settings
from app.execution import ExecutionContext
from app.sandbox import InMemorySandbox
from app.worker import AssessmentDispatcher


@pytest.fixture
def assessment(database):
    with database.SessionLocal() as db:
        project = models.Project(name="lifecycle")
        db.add(project)
        db.flush()
        target = models.Target(
            project_id=project.id,
            name="demo",
            image=settings.docker_target_image,
            url="http://demo-target:8080/",
        )
        db.add(target)
        db.flush()
        scope = models.AuthorizationScope(
            project_id=project.id,
            target_id=target.id,
            allowed_url=target.url,
            expires_at=models.now() + timedelta(minutes=5),
        )
        db.add(scope)
        db.flush()
        item = models.Assessment(
            project_id=project.id,
            target_id=target.id,
            scope_id=scope.id,
            profile="passive",
        )
        db.add(item)
        db.commit()
        return item.id


def read(database, assessment):
    with database.SessionLocal() as db:
        return db.get(models.Assessment, assessment)


@pytest.mark.parametrize("change", ["expiry", "image", "relationship"])
def test_execution_revalidates_policy(database, assessment, monkeypatch, change):
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, assessment)
        scope = db.get(models.AuthorizationScope, item.scope_id)
        if change == "expiry":
            scope.expires_at = models.now() - timedelta(seconds=1)
        elif change == "relationship":
            scope.project_id = (
                "mismatch"  # Test via the policy object instead of violating FK.
            )
            db.expunge(scope)
            from app.policy import PolicyError, validate

            with pytest.raises(PolicyError):
                validate(
                    db.get(models.Project, item.project_id),
                    db.get(models.Target, item.target_id),
                    scope,
                    item.profile,
                    settings.docker_allowed_target_images,
                )
            item.status = "cancelled"
        else:
            monkeypatch.setattr(settings, "docker_allowed_target_images", [])
        db.commit()
    called = []
    monkeypatch.setattr(InMemorySandbox, "execute", lambda *a: called.append(True))
    AssessmentDispatcher()._run(assessment, Event())
    assert read(database, assessment).status in {"failed", "cancelled"}
    assert not called


def test_running_visible_duplicate_claims_and_terminal_redispatch(
    database, assessment, monkeypatch
):
    entered, release = Event(), Event()
    original = InMemorySandbox.execute

    def blocked(self, *args):
        entered.set()
        assert release.wait(5)
        return original(self, *args)

    monkeypatch.setattr(InMemorySandbox, "execute", blocked)
    dispatcher = AssessmentDispatcher()
    thread = Thread(target=dispatcher._run, args=(assessment, Event()))
    thread.start()
    try:
        assert entered.wait(5)
        assert read(database, assessment).status == "running"
        dispatcher._run(assessment, Event())
    finally:
        release.set()
        thread.join(5)
    dispatcher._run(assessment, Event())
    assert read(database, assessment).status == "completed"
    with database.SessionLocal() as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(models.Attempt).where(
                            models.Attempt.assessment_id == assessment
                        )
                    )
                )
            )
            == 1
        )
        assert (
            len(
                list(
                    db.scalars(
                        select(models.Finding).where(
                            models.Finding.assessment_id == assessment
                        )
                    )
                )
            )
            == 3
        )


@pytest.mark.parametrize("reason", ["cancel", "timeout", "expiry", "shutdown"])
def test_active_execution_stops_and_cleans(database, assessment, monkeypatch, reason):
    entered, cleaned = Event(), Event()

    def blocking(self, *args):
        entered.set()
        while True:
            self.context.check()
            sleep(0.005)

    monkeypatch.setattr(InMemorySandbox, "execute", blocking)
    monkeypatch.setattr(InMemorySandbox, "cleanup", lambda self: cleaned.set() or True)
    if reason == "timeout":
        monkeypatch.setattr(settings, "assessment_timeout_seconds", 0.1)
    if reason == "expiry":
        with database.SessionLocal() as db:
            item = db.get(models.Assessment, assessment)
            db.get(models.AuthorizationScope, item.scope_id).expires_at = (
                models.now() + timedelta(seconds=0.2)
            )
            db.commit()
    dispatcher, cancel = AssessmentDispatcher(), Event()
    thread = Thread(target=dispatcher._run, args=(assessment, cancel))
    thread.start()
    try:
        assert entered.wait(5)
        if reason == "cancel":
            with database.SessionLocal() as db:
                db.get(models.Assessment, assessment).status = "cancelling"
                db.commit()
            cancel.set()
        elif reason == "shutdown":
            dispatcher._shutdown.set()
        thread.join(5)
        assert not thread.is_alive()
        assert cleaned.is_set()
        item = read(database, assessment)
        assert (
            item.status
            == {
                "cancel": "cancelled",
                "timeout": "failed",
                "expiry": "failed",
                "shutdown": "recovering",
            }[reason]
        )
        assert item.result["cleanup_verified"]
    finally:
        cancel.set()
        thread.join(5)


def interrupted(database, assessment, number=1, status="running"):
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, assessment)
        item.status, item.cleanup_pending = status, True
        for n in range(1, number + 1):
            db.add(
                models.Attempt(
                    assessment_id=item.id, number=n, backend="inmemory", resources={}
                )
            )
        db.commit()


@pytest.mark.parametrize("mode", ["retry", "limit", "cancel", "expired", "cleanup"])
def test_recovery_policy(database, assessment, monkeypatch, mode):
    interrupted(
        database,
        assessment,
        2 if mode == "limit" else 1,
        "cancelling" if mode == "cancel" else "running",
    )
    if mode == "expired":
        with database.SessionLocal() as db:
            item = db.get(models.Assessment, assessment)
            db.get(models.AuthorizationScope, item.scope_id).expires_at = (
                models.now() - timedelta(seconds=1)
            )
            db.commit()
    if mode == "cleanup":
        monkeypatch.setattr(InMemorySandbox, "cleanup", lambda self: False)
    dispatcher = AssessmentDispatcher()
    dispatcher.recover()
    expected = (
        "queued" if mode == "retry" else "cancelled" if mode == "cancel" else "failed"
    )
    assert read(database, assessment).status == expected
    if mode == "retry":
        dispatcher._run(assessment, Event())
        item = read(database, assessment)
        assert item.status == "completed"
        assert item.result["attempt"] == 2
        assert item.result["finding_count"] == 3
    if mode == "cleanup":
        assert read(database, assessment).cleanup_pending
        monkeypatch.setattr(InMemorySandbox, "cleanup", lambda self: True)
        dispatcher.recover()
        assert not read(database, assessment).cleanup_pending
        assert read(database, assessment).status == "failed"


def test_only_one_dispatcher_and_lock_loss_stops_work(database):
    first, second = AssessmentDispatcher(), AssessmentDispatcher()
    first.start()
    try:
        with pytest.raises(RuntimeError, match="Another"):
            second.start()
        with database.engine.connect() as connection:
            pid = connection.scalar(
                text(
                    "SELECT pid FROM pg_locks WHERE locktype='advisory' AND objid=7342101 AND database=(SELECT oid FROM pg_database WHERE datname=current_database())"
                )
            )
            connection.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            connection.commit()
        assert first._lost.wait(5)
        assert not first.ready
        with pytest.raises(Exception, match="interrupted"):
            ExecutionContext(
                Event(), Event(), monotonic() + 5, lambda: not first._lost.is_set()
            ).check()
    finally:
        first.stop()


def test_recovery_does_not_requeue_after_ownership_loss(
    database, assessment, monkeypatch
):
    interrupted(database, assessment)
    dispatcher = AssessmentDispatcher()

    def lose_ownership(self):
        dispatcher._lost.set()
        return True

    monkeypatch.setattr(InMemorySandbox, "cleanup", lose_ownership)
    with pytest.raises(RuntimeError, match="ownership lost"):
        dispatcher.recover()
    item = read(database, assessment)
    assert item.status == "recovering"
    assert item.cleanup_pending

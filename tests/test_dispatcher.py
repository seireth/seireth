"""Regression tests through the real PostgreSQL-backed dispatcher."""

from datetime import timedelta
from threading import Event, Thread
from time import monotonic, sleep

import pytest
from sqlalchemy import select, text

from app import models
from app.config import settings
from app.execution import ExecutionContext
from app.plugins import BY_ID, Plugin
from app.sandbox import CleanupOutcome, InMemorySandbox, new_journal
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
    monkeypatch.setattr(
        InMemorySandbox, "cleanup", lambda self: cleaned.set() or CleanupOutcome(True)
    )
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
                    assessment_id=item.id,
                    number=n,
                    backend="inmemory",
                    resources={},
                    operation_journal=new_journal(),
                )
            )
        db.commit()


def test_corrupt_journal_cannot_authorize_cleanup_or_retry(database, assessment):
    interrupted(database, assessment)
    with database.SessionLocal() as db:
        attempt = db.scalar(
            select(models.Attempt).where(models.Attempt.assessment_id == assessment)
        )
        attempt.operation_journal = {}
        db.commit()
    AssessmentDispatcher().recover()
    item = read(database, assessment)
    assert item.status == "failed" and item.cleanup_pending
    assert item.result["cleanup_verified"] is False
    assert item.result["cleanup_reason"] == "invalid operation journal"


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
        monkeypatch.setattr(
            InMemorySandbox,
            "cleanup",
            lambda self: CleanupOutcome(False, "daemon unavailable"),
        )
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
        assert item.plugins == ["security-headers"]
        assert item.result["attempt"] == 2
        assert item.result["finding_count"] == 3
        assert item.result["plugins"] == [
            {"id": "security-headers", "finding_count": 3}
        ]
    if mode == "cleanup":
        assert read(database, assessment).cleanup_pending
        monkeypatch.setattr(
            InMemorySandbox, "cleanup", lambda self: CleanupOutcome(True)
        )
        dispatcher.recover()
        assert not read(database, assessment).cleanup_pending
        assert read(database, assessment).status == "failed"


def test_plugin_failure_persists_no_findings_after_verified_cleanup(
    database, assessment, monkeypatch
):
    def broken(headers, url):
        raise RuntimeError("synthetic plugin failure")

    monkeypatch.setitem(
        BY_ID,
        "security-headers",
        Plugin(
            "security-headers",
            "Broken",
            "Test failure",
            ("passive",),
            broken,
        ),
    )
    AssessmentDispatcher()._run(assessment, Event())
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, assessment)
        assert item.status == "failed"
        assert item.result["cleanup_verified"]
        assert item.findings == []


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
    dispatcher = AssessmentDispatcher()
    # Settle attempts left by the preceding ownership-loss test before injecting
    # loss into this specific attempt's recovery.
    dispatcher.recover()
    interrupted(database, assessment)

    def lose_ownership(self):
        dispatcher._lost.set()
        return CleanupOutcome(True)

    monkeypatch.setattr(InMemorySandbox, "cleanup", lose_ownership)
    with pytest.raises(RuntimeError, match="ownership lost"):
        dispatcher.recover()
    item = read(database, assessment)
    assert item.status == "recovering"
    assert item.cleanup_pending


@pytest.fixture
def pending_docker(database, assessment):
    from uuid import uuid4

    from app.sandbox import DockerSandbox, new_journal

    attempt_id = str(uuid4())
    journal = new_journal()
    journal["resources"]["network"]["state"] = "uncertain"
    sandbox = DockerSandbox(
        settings.docker_target_image,
        runner_image=settings.docker_runner_image,
        assessment_id=assessment,
        attempt_id=attempt_id,
        operation_journal=journal,
    )
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, assessment)
        item.status, item.cleanup_pending = "failed", True
        item.result = {
            "error": "original execution failure",
            "cleanup_verified": False,
            "cleanup_reason": "creation outcome unknown",
        }
        db.add(
            models.Attempt(
                id=attempt_id,
                assessment_id=assessment,
                number=1,
                backend="docker",
                resources=sandbox.resources,
                operation_journal=journal,
                error="original execution failure",
            )
        )
        db.commit()
    yield sandbox
    with database.SessionLocal() as db:
        # These are synthetic daemon resources, so do not leave an artificial
        # pending attempt for unrelated tests sharing the disposable database.
        db.get(models.Assessment, assessment).cleanup_pending = False
        db.commit()


def test_pending_cleanup_survives_restart_and_resolves_once(
    database, assessment, pending_docker, monkeypatch
):
    from fake_docker import FakeDocker

    daemon = FakeDocker()
    daemon.install(monkeypatch)
    for _ in range(3):
        AssessmentDispatcher().recover(failed_only=True)
        item = read(database, assessment)
        assert item.status == "failed" and item.cleanup_pending
        assert "network" in item.result["cleanup_reason"]
    daemon.add(pending_docker, "network")
    dispatcher = AssessmentDispatcher()
    dispatcher.recover(failed_only=True)
    dispatcher.recover(failed_only=True)
    item = read(database, assessment)
    assert item.status == "failed"
    assert not item.cleanup_pending and item.result["cleanup_verified"]
    assert item.result["cleanup_reason"] is None
    assert item.result["error"] == "original execution failure"
    assert not daemon.live
    with database.SessionLocal() as db:
        events = list(
            db.scalars(
                select(models.AuditEvent).where(
                    models.AuditEvent.resource_id == assessment,
                    models.AuditEvent.action == "assessment.cleanup_verified",
                )
            )
        )
        assert len(events) == 1
        assert (
            db.get(models.Attempt, pending_docker.attempt_id).error
            == "original execution failure"
        )


def test_recovery_fences_old_journal_writer(
    database, assessment, pending_docker, monkeypatch
):
    from fake_docker import FakeDocker

    from app.execution import Interrupted

    FakeDocker().install(monkeypatch)
    dispatcher = AssessmentDispatcher()
    stale = dispatcher._journal_writer(
        assessment,
        pending_docker.attempt_id,
        pending_docker.journal["owner"],
        recovery=True,
    )
    dispatcher.recover(failed_only=True)
    with pytest.raises(Interrupted, match="no longer owns"):
        stale(pending_docker.journal)


def test_advancing_checks_durable_cancellation(database, assessment, pending_docker):
    from app.execution import Cancelled

    with database.SessionLocal() as db:
        db.get(models.Assessment, assessment).status = "cancelling"
        db.commit()
    dispatcher = AssessmentDispatcher()
    write = dispatcher._journal_writer(
        assessment, pending_docker.attempt_id, pending_docker.journal["owner"]
    )
    with pytest.raises(Cancelled):
        write(pending_docker.journal, advancing=True)
    write(pending_docker.journal)  # Cancellation must still permit cleanup.
    with database.SessionLocal() as db:
        db.get(models.Assessment, assessment).status = "failed"
        db.commit()


def test_periodic_cleanup_skips_active_attempts(
    database, assessment, pending_docker, monkeypatch
):
    from fake_docker import FakeDocker

    daemon = FakeDocker()
    daemon.install(monkeypatch)
    dispatcher = AssessmentDispatcher()
    dispatcher._events[assessment] = Event()
    dispatcher.recover(failed_only=True)
    assert not daemon.calls
    dispatcher._events.clear()
    with database.SessionLocal() as db:
        db.get(models.Assessment, assessment).status = "running"
        db.commit()
    dispatcher.recover(failed_only=True)
    assert not daemon.calls
    with database.SessionLocal() as db:
        db.get(models.Assessment, assessment).status = "failed"
        db.commit()


def test_background_cleanup_runs_without_blocking_new_assessments(
    database, assessment, pending_docker, monkeypatch
):
    from fake_docker import FakeDocker

    from app import worker

    daemon = FakeDocker()
    daemon.install(monkeypatch)
    monkeypatch.setattr(worker, "RECONCILE_INTERVAL_SECONDS", 0.02)
    dispatcher = AssessmentDispatcher()
    dispatcher.start()
    try:
        assert dispatcher.ready
        with database.SessionLocal() as db:
            old = db.get(models.Assessment, assessment)
            new = models.Assessment(
                project_id=old.project_id,
                target_id=old.target_id,
                scope_id=old.scope_id,
                profile="passive",
            )
            db.add(new)
            db.commit()
            new_id = new.id
        dispatcher.submit(new_id)
        deadline = monotonic() + 5
        while read(database, new_id).status != "completed" and monotonic() < deadline:
            sleep(0.01)
        assert read(database, new_id).status == "completed"
        assert read(database, assessment).cleanup_pending
        daemon.add(pending_docker, "network")
        deadline = monotonic() + 5
        while read(database, assessment).cleanup_pending and monotonic() < deadline:
            sleep(0.01)
        assert not read(database, assessment).cleanup_pending
    finally:
        dispatcher.stop()
    assert dispatcher._reconciler is None


def test_cleanup_stops_on_owner_loss(database, assessment, pending_docker, monkeypatch):
    from fake_docker import FakeDocker

    from app.execution import Interrupted

    daemon = FakeDocker()
    daemon.install(monkeypatch)
    daemon.add(pending_docker, "network")
    dispatcher = AssessmentDispatcher()
    dispatcher._lost.set()
    pending_docker.persist_journal = dispatcher._journal_writer(
        assessment,
        pending_docker.attempt_id,
        pending_docker.journal["owner"],
        recovery=True,
    )
    assert not pending_docker.cleanup().verified
    assert not daemon.calls
    with pytest.raises(Interrupted):
        pending_docker.persist_journal(pending_docker.journal)

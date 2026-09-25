"""Regression tests through the real PostgreSQL-backed dispatcher."""

from datetime import timedelta
from threading import Event, Thread
from time import monotonic, sleep

import pytest
from sqlalchemy import func, select, text

from app import models, worker
from app.config import settings
from app.execution import ExecutionContext
from app.plugins.base import Plugin, PluginManifest, PluginRegistry
from app.plugins.security_headers import PLUGIN as SECURITY_HEADERS_PLUGIN
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
            plugins=["security-headers"],
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
            other_project = models.Project(name="other")
            db.add(other_project)
            db.flush()
            scope.project_id = other_project.id
        else:
            monkeypatch.setattr(settings, "docker_allowed_target_images", [])
        db.commit()
    called = []
    monkeypatch.setattr(InMemorySandbox, "execute", lambda *a: called.append(True))
    AssessmentDispatcher()._run(assessment, Event())
    assert read(database, assessment).status == "failed"
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
            db.scalar(
                select(func.count())
                .select_from(models.Attempt)
                .where(models.Attempt.assessment_id == assessment)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(models.Finding)
                .where(models.Finding.assessment_id == assessment)
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
        dispatcher.recover(include_failed_cleanup=True)
        assert not read(database, assessment).cleanup_pending
        assert read(database, assessment).status == "failed"


def test_plugin_failure_persists_no_findings_after_verified_cleanup(
    database, assessment, monkeypatch
):
    calls = []

    def broken(observation):
        calls.append(observation.url)
        raise RuntimeError("synthetic plugin failure")

    monkeypatch.setattr(
        worker,
        "plugin_registry",
        PluginRegistry(
            (
                SECURITY_HEADERS_PLUGIN,
                Plugin(
                    PluginManifest(
                        id="broken", name="Broken", description="Test failure"
                    ),
                    broken,
                ),
            ),
        ),
    )
    with database.SessionLocal() as db:
        db.get(models.Assessment, assessment).plugins = ["security-headers", "broken"]
        db.commit()
    AssessmentDispatcher()._run(assessment, Event())
    assert len(calls) == 1
    with database.SessionLocal() as db:
        item = db.get(models.Assessment, assessment)
        assert item.status == "failed"
        assert item.result["cleanup_verified"]
        assert item.findings == []
        assert (
            db.scalar(
                select(models.Evidence.id).where(
                    models.Evidence.assessment_id == assessment
                )
            )
            is None
        )


def test_running_dispatcher_recovers_transient_finalization_failure(
    database, assessment, monkeypatch, wait_until
):
    original_finish = worker.finish
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        item = args[1]
        if item.id != assessment:
            return original_finish(*args, **kwargs)
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic finalization failure")
        return original_finish(*args, **kwargs)

    monkeypatch.setattr(worker, "finish", fail_once)
    monkeypatch.setattr(worker, "RECONCILE_INTERVAL_SECONDS", 0.02)
    dispatcher = AssessmentDispatcher()
    dispatcher.start()
    try:
        wait_until(
            lambda: read(database, assessment).status,
            lambda status: status == "completed",
            description="assessment completion after finalization recovery",
        )
        item = read(database, assessment)
        assert item.status == "completed"
        assert item.result["attempt"] == 2
        assert calls == 2
    finally:
        dispatcher.stop()


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
    return sandbox


def test_pending_cleanup_survives_restart_and_resolves_once(
    database, assessment, pending_docker, fake_docker
):
    for _ in range(3):
        AssessmentDispatcher().recover(include_failed_cleanup=True)
        item = read(database, assessment)
        assert item.status == "failed" and item.cleanup_pending
        assert "network" in item.result["cleanup_reason"]
    fake_docker.add(pending_docker, "network")
    dispatcher = AssessmentDispatcher()
    dispatcher.recover(include_failed_cleanup=True)
    dispatcher.recover(include_failed_cleanup=True)
    item = read(database, assessment)
    assert item.status == "failed"
    assert not item.cleanup_pending and item.result["cleanup_verified"]
    assert item.result["cleanup_reason"] is None
    assert item.result["error"] == "original execution failure"
    assert not fake_docker.live
    with database.SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(models.AuditEvent)
                .where(
                    models.AuditEvent.resource_id == assessment,
                    models.AuditEvent.action == "assessment.cleanup_verified",
                )
            )
            == 1
        )
        assert (
            db.get(models.Attempt, pending_docker.attempt_id).error
            == "original execution failure"
        )


def test_recovery_rejects_stale_journal_writes(
    database, assessment, pending_docker, fake_docker
):
    from app.execution import Interrupted

    dispatcher = AssessmentDispatcher()
    stale = dispatcher._journal_writer(
        assessment,
        pending_docker.attempt_id,
        pending_docker.journal["owner"],
        recovery=True,
    )
    dispatcher.recover(include_failed_cleanup=True)
    with pytest.raises(Interrupted, match="no longer owns"):
        stale(pending_docker.journal)


def test_journal_advancement_rejects_persisted_cancellation(
    database, assessment, pending_docker
):
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


def test_periodic_recovery_skips_owned_attempts_and_recovers_orphans(
    database, assessment, pending_docker, fake_docker
):
    dispatcher = AssessmentDispatcher()
    dispatcher._events[assessment] = Event()
    dispatcher.recover(include_failed_cleanup=True)
    assert not fake_docker.calls
    dispatcher._events.clear()
    with database.SessionLocal() as db:
        db.get(models.Assessment, assessment).status = "running"
        db.commit()
    dispatcher.recover(include_failed_cleanup=True)
    assert fake_docker.calls
    item = read(database, assessment)
    assert item.status == "failed"
    assert item.cleanup_pending
    with database.SessionLocal() as db:
        db.get(models.Assessment, assessment).status = "failed"
        db.commit()


def test_background_cleanup_runs_without_blocking_new_assessments(
    database, assessment, pending_docker, monkeypatch, fake_docker, wait_until
):
    from app import worker

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
                plugins=["security-headers"],
            )
            db.add(new)
            db.commit()
            new_id = new.id
        dispatcher.submit(new_id)
        wait_until(
            lambda: read(database, new_id).status,
            lambda status: status == "completed",
            description="new assessment completion during background cleanup",
        )
        assert read(database, new_id).status == "completed"
        assert read(database, assessment).cleanup_pending
        fake_docker.add(pending_docker, "network")
        wait_until(
            lambda: read(database, assessment).cleanup_pending,
            lambda pending: not pending,
            description="background cleanup verification",
        )
        assert not read(database, assessment).cleanup_pending
    finally:
        dispatcher.stop()
    assert dispatcher._reconciler is None


def test_failed_cleanup_runs_after_dispatcher_becomes_ready(
    database, pending_docker, monkeypatch
):
    from app.sandbox import DockerSandbox

    entered, release = Event(), Event()

    def blocked_cleanup(self):
        entered.set()
        assert release.wait(5)
        return CleanupOutcome(False, "daemon unavailable")

    monkeypatch.setattr(DockerSandbox, "cleanup", blocked_cleanup)
    dispatcher = AssessmentDispatcher()
    dispatcher.start()
    try:
        assert dispatcher.ready
        assert entered.wait(5)
        assert dispatcher.ready
    finally:
        release.set()
        dispatcher.stop()


def test_cleanup_stops_on_owner_loss(database, assessment, pending_docker, fake_docker):
    from app.execution import Interrupted

    fake_docker.add(pending_docker, "network")
    dispatcher = AssessmentDispatcher()
    dispatcher._lost.set()
    pending_docker.persist_journal = dispatcher._journal_writer(
        assessment,
        pending_docker.attempt_id,
        pending_docker.journal["owner"],
        recovery=True,
    )
    assert not pending_docker.cleanup().verified
    assert not fake_docker.calls
    with pytest.raises(Interrupted):
        pending_docker.persist_journal(pending_docker.journal)

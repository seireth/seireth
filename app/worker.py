"""Single-owner dispatcher with durable claims and one crash-recovery retry."""

import logging
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from sqlalchemy import select, text

from . import db as database
from . import models
from .config import settings
from .execution import Cancelled, ExecutionContext, Interrupted
from .lifecycle import audit, finish, transition
from .orchestrator import Outcome, execute, sandbox_for
from .plugins import select_plugins
from .policy import PolicyError, validate
from .sandbox import new_journal, validate_journal

logger = logging.getLogger(__name__)
OWNER_LOCK = 7342101
RECONCILE_INTERVAL_SECONDS = 30


def latest_attempt(db, assessment_id):
    return db.scalar(
        select(models.Attempt)
        .where(models.Attempt.assessment_id == assessment_id)
        .order_by(models.Attempt.number.desc())
        .limit(1)
    )


class AssessmentDispatcher:
    def __init__(self):
        self._events = {}
        self._lock = Lock()
        self._executor = None
        self._owner = None
        self._monitor = None
        self._shutdown = Event()
        self._lost = Event()
        self._monitor_stop = Event()
        self._reconciler = None
        self._reconcile_lock = Lock()
        self._owner_pid = None

    @property
    def ready(self):
        return (
            self._executor is not None
            and not self._shutdown.is_set()
            and not self._lost.is_set()
        )

    def start(self):
        self._shutdown.clear()
        self._lost.clear()
        self._monitor_stop.clear()
        self._owner = database.engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        )
        try:
            if not self._owner.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": OWNER_LOCK}
            ):
                raise RuntimeError("Another Seireth dispatcher owns this database")
            self._owner_pid = self._owner.scalar(text("SELECT pg_backend_pid()"))
            self._executor = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="seireth"
            )
            self._monitor = Thread(target=self._watch_owner, daemon=True)
            self._monitor.start()
            self.recover()
            self._reconciler = Thread(target=self._watch_cleanup, daemon=True)
            self._reconciler.start()
        except BaseException:
            self.stop()
            raise

    def _watch_owner(self):
        while not self._monitor_stop.wait(0.2):
            try:
                owned = self._owner.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() AND objid=:key AND granted)"
                    ),
                    {"key": OWNER_LOCK},
                )
                if not owned:
                    raise RuntimeError("dispatcher ownership lost")
            except Exception:
                logger.exception("dispatcher ownership lost; interrupting assessments")
                self._lost.set()
                return

    def stop(self):
        self._shutdown.set()
        if self._reconciler:
            self._reconciler.join()
            self._reconciler = None
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
        self._monitor_stop.set()
        if self._monitor:
            self._monitor.join(timeout=10)
            self._monitor = None
        if self._owner:
            try:
                self._owner.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": OWNER_LOCK}
                )
            except Exception:
                self._owner.invalidate()
            self._owner.close()
            self._owner = None
        self._owner_pid = None
        self._events.clear()

    def submit(self, assessment_id):
        if not self.ready:
            return  # The persisted queued record will be recovered at startup.
        with self._lock:
            if assessment_id in self._events:
                return
            event = self._events[assessment_id] = Event()
            self._executor.submit(self._run, assessment_id, event)

    def cancel(self, assessment_id):
        with self._lock:
            if event := self._events.get(assessment_id):
                event.set()

    def _policy(self, db, assessment):
        project = db.get(models.Project, assessment.project_id)
        target = db.get(models.Target, assessment.target_id)
        scope = db.get(models.AuthorizationScope, assessment.scope_id)
        validate(
            project,
            target,
            scope,
            assessment.profile,
            settings.docker_allowed_target_images,
        )
        try:
            select_plugins(assessment.plugins, assessment.profile)
        except ValueError as exc:
            raise PolicyError(str(exc)) from exc
        return target, scope

    def _assert_owner(self, db):
        if self._lost.is_set():
            raise Interrupted("dispatcher ownership lost")
        if self._owner_pid is not None and not db.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=:pid AND objid=:key AND granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database()))"
            ),
            {"pid": self._owner_pid, "key": OWNER_LOCK},
        ):
            self._lost.set()
            raise Interrupted("dispatcher ownership lost")

    def _journal_writer(self, assessment_id, attempt_id, token, *, recovery=False):
        def persist(journal, advancing=False):
            with database.SessionLocal() as db:
                item = db.get(models.Assessment, assessment_id, with_for_update=True)
                self._assert_owner(db)
                attempt = db.get(models.Attempt, attempt_id)
                latest = latest_attempt(db, assessment_id)
                allowed = (
                    {"recovering", "cancelling", "failed"}
                    if recovery
                    else {"running", "cancelling"}
                )
                if (
                    not item
                    or not attempt
                    or not latest
                    or latest.id != attempt_id
                    or item.status not in allowed
                    or not attempt.operation_journal
                    or attempt.operation_journal["owner"] != token
                    or journal["owner"] != token
                ):
                    raise Interrupted("execution attempt no longer owns its journal")
                if recovery and self._shutdown.is_set():
                    raise Interrupted("cleanup reconciliation stopped")
                if advancing:
                    if item.status == "cancelling":
                        raise Cancelled("assessment cancelled")
                    if self._shutdown.is_set():
                        raise Interrupted("execution interrupted")
                attempt.operation_journal = deepcopy(journal)
                db.commit()

        return persist

    def _watch_cleanup(self):
        while not self._shutdown.wait(RECONCILE_INTERVAL_SECONDS):
            if self._lost.is_set():
                return
            try:
                self.recover(failed_only=True)
            except Exception:
                logger.exception("pending cleanup reconciliation failed")

    def _run(self, assessment_id, cancel_event):
        try:
            if self._shutdown.is_set() or self._lost.is_set():
                return
            with database.SessionLocal() as db:
                item = db.get(models.Assessment, assessment_id, with_for_update=True)
                if not item or item.status != "queued":
                    return
                try:
                    target, scope = self._policy(db, item)
                    previous = latest_attempt(db, item.id)
                    number = previous.number + 1 if previous else 1
                    if number > 2:
                        raise PolicyError("crash recovery retry limit reached")
                except PolicyError as exc:
                    item.result = {
                        "error": str(exc),
                        "cleanup_verified": True,
                        "cleanup_reason": None,
                        "sandbox_backend": settings.sandbox_backend,
                        "completed_at": models.now().isoformat(),
                    }
                    transition(db, item, "failed")
                    db.commit()
                    return
                attempt = models.Attempt(
                    id=str(uuid4()),
                    assessment_id=item.id,
                    number=number,
                    backend=settings.sandbox_backend,
                    resources={},
                    operation_journal=new_journal(),
                )
                expires = scope.expires_at
                seconds = min(
                    settings.assessment_timeout_seconds,
                    (expires - datetime.now(timezone.utc)).total_seconds(),
                )
                context = ExecutionContext(
                    cancel_event,
                    self._shutdown,
                    monotonic() + max(0, seconds),
                    lambda: not self._lost.is_set(),
                )
                sandbox = sandbox_for(
                    attempt,
                    target,
                    scope,
                    context,
                    self._journal_writer(
                        item.id, attempt.id, attempt.operation_journal["owner"]
                    ),
                )
                attempt.resources = getattr(sandbox, "resources", {})
                db.add(attempt)
                item.cleanup_pending = True
                transition(db, item, "running", {"attempt": number})
                db.commit()
                attempt_id, url, plugin_ids = (
                    attempt.id,
                    scope.allowed_url,
                    list(item.plugins),
                )
            outcome = execute(sandbox, url, context, plugin_ids)
            if self._lost.is_set():
                return  # A new owner must reconcile; never overwrite its decisions.
            # The cancellation row lock serializes cancellation against completion.
            with database.SessionLocal() as db:
                item = db.get(models.Assessment, assessment_id, with_for_update=True)
                latest = latest_attempt(db, assessment_id)
                if (
                    self._lost.is_set()
                    or item.status not in {"running", "cancelling"}
                    or not latest
                    or latest.id != attempt_id
                ):
                    return
                attempt = db.get(models.Attempt, attempt_id)
                self._assert_owner(db)
                if (
                    hasattr(sandbox, "journal")
                    and attempt.operation_journal["owner"] != sandbox.journal["owner"]
                ):
                    return
                if item.status == "cancelling" and outcome.cleanup_verified:
                    outcome.status, outcome.error = "cancelled", "assessment cancelled"
                finish(db, item, attempt, outcome)
                db.commit()
        except Exception:
            # A later dispatcher startup revisits any nonterminal record left here.
            logger.exception("worker could not finalize assessment %s", assessment_id)
        finally:
            with self._lock:
                self._events.pop(assessment_id, None)

    def recover(self, *, failed_only=False):
        # Never reconcile active workers in the periodic pass. Startup recovery
        # runs before the API accepts requests and before queued work is submitted.
        with self._reconcile_lock:
            self._recover(failed_only=failed_only)

    def _recover(self, *, failed_only=False):
        with database.SessionLocal() as db:
            ids = list(
                db.scalars(
                    select(models.Assessment.id)
                    .where(
                        (
                            models.Assessment.status.in_(
                                ["running", "recovering", "cancelling"]
                            )
                        )
                        | models.Assessment.cleanup_pending
                    )
                    .where(
                        models.Assessment.status == "failed" if failed_only else True
                    )
                )
            )
        for assessment_id in ids:
            if self._shutdown.is_set():
                return
            with self._lock:
                if assessment_id in self._events:
                    continue
            if self._lost.is_set():
                raise RuntimeError("dispatcher ownership lost during recovery")
            with database.SessionLocal() as db:
                item = db.get(models.Assessment, assessment_id, with_for_update=True)
                self._assert_owner(db)
                if (
                    item.status not in {"running", "recovering", "cancelling"}
                    and not item.cleanup_pending
                ):
                    continue
                attempt = latest_attempt(db, item.id)
                try:
                    if not attempt:
                        raise ValueError("execution attempt missing")
                    validate_journal(attempt.operation_journal)
                except ValueError as exc:
                    if item.status != "failed":
                        transition(db, item, "failed", {"error": str(exc)})
                    item.cleanup_pending = True
                    item.result = {
                        **(item.result or {}),
                        "cleanup_verified": False,
                        "cleanup_reason": str(exc),
                    }
                    db.commit()
                    continue
                original_status = item.status
                if original_status == "running":
                    transition(db, item, "recovering", {"attempt": attempt.number})
                journal = deepcopy(attempt.operation_journal)
                token = journal["owner"] = str(uuid4())
                attempt.operation_journal = journal
                attempt_id = attempt.id
                db.commit()
                sandbox = sandbox_for(
                    attempt,
                    persist_journal=self._journal_writer(
                        item.id, attempt.id, token, recovery=True
                    ),
                )
            cleanup = sandbox.cleanup()
            with database.SessionLocal() as db:
                item = db.get(models.Assessment, assessment_id, with_for_update=True)
                self._assert_owner(db)
                attempt = db.get(models.Attempt, attempt_id)
                if attempt.operation_journal["owner"] != token or item.status not in {
                    "recovering",
                    "cancelling",
                    "failed",
                }:
                    continue
                cleaned = cleanup.verified
                attempt.cleanup_verified = cleaned
                attempt.finished_at = attempt.finished_at or models.now()
                item.cleanup_pending = not cleaned
                if original_status == "failed":
                    item.result = {
                        **(item.result or {}),
                        "cleanup_verified": cleaned,
                        "cleanup_reason": cleanup.reason,
                    }
                    if cleaned:
                        audit(
                            db, item.project_id, "assessment.cleanup_verified", item.id
                        )
                elif not cleaned:
                    finish(
                        db,
                        item,
                        attempt,
                        Outcome(
                            "failed",
                            (item.result or {}).get("error")
                            or "sandbox cleanup could not be verified",
                            False,
                            cleanup_reason=cleanup.reason,
                        ),
                    )
                elif item.status == "cancelling":
                    finish(
                        db,
                        item,
                        attempt,
                        Outcome("cancelled", "assessment cancelled", True),
                    )
                else:
                    try:
                        self._policy(db, item)
                        if attempt.number >= 2:
                            raise PolicyError("crash recovery retry limit reached")
                    except PolicyError as exc:
                        finish(db, item, attempt, Outcome("failed", str(exc), True))
                    else:
                        attempt.error = "execution interrupted"
                        item.result = None
                        transition(
                            db, item, "queued", {"retry_after_attempt": attempt.number}
                        )
                db.commit()
        if failed_only:
            return
        with database.SessionLocal() as db:
            queued = list(
                db.scalars(
                    select(models.Assessment.id).where(
                        models.Assessment.status == "queued"
                    )
                )
            )
        for assessment_id in queued:
            self.submit(assessment_id)


dispatcher = AssessmentDispatcher()

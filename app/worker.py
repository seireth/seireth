"""Single-owner dispatcher with durable claims and one crash-recovery retry."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from sqlalchemy import func, select, text

from . import models
from .config import settings
from .db import SessionLocal, engine
from .execution import ExecutionContext
from .lifecycle import audit, finish, transition
from .orchestrator import Outcome, execute, sandbox_for
from .policy import PolicyError, validate

logger = logging.getLogger(__name__)
OWNER_LOCK = 7342101


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
        self._owner = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            if not self._owner.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": OWNER_LOCK}
            ):
                raise RuntimeError("Another Seireth dispatcher owns this database")
            self._executor = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="seireth"
            )
            self._monitor = Thread(target=self._watch_owner, daemon=True)
            self._monitor.start()
            self.recover()
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
        return target, scope

    def _run(self, assessment_id, cancel_event):
        try:
            if self._shutdown.is_set() or self._lost.is_set():
                return
            with SessionLocal() as db:
                item = db.scalar(
                    select(models.Assessment)
                    .where(models.Assessment.id == assessment_id)
                    .with_for_update()
                )
                if not item or item.status != "queued":
                    return
                try:
                    target, scope = self._policy(db, item)
                    number = 1 + (
                        db.scalar(
                            select(func.max(models.Attempt.number)).where(
                                models.Attempt.assessment_id == item.id
                            )
                        )
                        or 0
                    )
                    if number > 2:
                        raise PolicyError("crash recovery retry limit reached")
                except PolicyError as exc:
                    item.result = {
                        "error": str(exc),
                        "cleanup_verified": True,
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
                sandbox = sandbox_for(attempt, target, scope, context)
                attempt.resources = getattr(sandbox, "resources", {})
                db.add(attempt)
                item.cleanup_pending = True
                transition(db, item, "running", {"attempt": number})
                db.commit()
                attempt_id, url = attempt.id, scope.allowed_url
            outcome = execute(sandbox, url, context)
            if self._lost.is_set():
                return  # A new owner must reconcile; never overwrite its decisions.
            # The cancellation row lock serializes cancellation against completion.
            with SessionLocal() as db:
                item = db.scalar(
                    select(models.Assessment)
                    .where(models.Assessment.id == assessment_id)
                    .with_for_update()
                )
                latest = db.scalar(
                    select(models.Attempt.id)
                    .where(models.Attempt.assessment_id == assessment_id)
                    .order_by(models.Attempt.number.desc())
                    .limit(1)
                )
                if (
                    self._lost.is_set()
                    or item.status not in {"running", "cancelling"}
                    or latest != attempt_id
                ):
                    return
                attempt = db.get(models.Attempt, attempt_id)
                if item.status == "cancelling" and outcome.cleanup_verified:
                    outcome.status, outcome.error = "cancelled", "assessment cancelled"
                finish(db, item, attempt, outcome)
                db.commit()
        except Exception:
            # Preserve the durable nonterminal attempt for startup reconciliation.
            logger.exception("worker could not finalize assessment %s", assessment_id)
        finally:
            with self._lock:
                self._events.pop(assessment_id, None)

    def recover(self):
        with SessionLocal() as db:
            ids = list(
                db.scalars(
                    select(models.Assessment.id).where(
                        (
                            models.Assessment.status.in_(
                                ["running", "recovering", "cancelling"]
                            )
                        )
                        | models.Assessment.cleanup_pending
                    )
                )
            )
        for assessment_id in ids:
            if self._lost.is_set():
                raise RuntimeError("dispatcher ownership lost during recovery")
            with SessionLocal() as db:
                item = db.scalar(
                    select(models.Assessment)
                    .where(models.Assessment.id == assessment_id)
                    .with_for_update()
                )
                if (
                    item.status not in {"running", "recovering", "cancelling"}
                    and not item.cleanup_pending
                ):
                    continue
                attempt = db.scalar(
                    select(models.Attempt)
                    .where(models.Attempt.assessment_id == item.id)
                    .order_by(models.Attempt.number.desc())
                )
                if not attempt:
                    transition(
                        db, item, "failed", {"error": "execution attempt missing"}
                    )
                    item.cleanup_pending = False
                    db.commit()
                    continue
                original_status = item.status
                if original_status == "running":
                    transition(db, item, "recovering", {"attempt": attempt.number})
                    db.commit()
                cleaned = sandbox_for(attempt).cleanup()
                if self._lost.is_set():
                    raise RuntimeError("dispatcher ownership lost during recovery")
                attempt.cleanup_verified = cleaned
                attempt.finished_at = models.now()
                item.cleanup_pending = not cleaned
                if original_status == "failed":
                    item.result = {**(item.result or {}), "cleanup_verified": cleaned}
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
                            "failed", "sandbox cleanup could not be verified", False
                        ),
                    )
                elif original_status == "cancelling":
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
        with SessionLocal() as db:
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

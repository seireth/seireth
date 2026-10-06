"""Single-owner dispatcher with durable claims and one crash-recovery retry."""

import logging
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from sqlalchemy import select, text

from ..core.config import settings
from ..core.constraints import MAX_ASSESSMENT_ATTEMPTS
from ..persistence import db as database
from ..persistence import models
from ..plugins.registry import registry as plugin_registry
from .execution import Cancelled, ExecutionContext, Interrupted
from .images import DockerUnavailable, ImageUnavailable, require_local_image
from .lifecycle import audit, finish, transition
from .orchestrator import Outcome, execute, sandbox_for
from .policy import PolicyError, validate
from .sandbox import new_journal, validate_journal

logger = logging.getLogger(__name__)
OWNER_LOCK = 7342101
RECONCILE_INTERVAL_SECONDS = 30
_OWNERSHIP_LOST = "dispatcher ownership lost"
_ASSESSMENT_CANCELLED = "assessment cancelled"


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
                    raise RuntimeError(_OWNERSHIP_LOST)
            except Exception:
                logger.exception("dispatcher ownership lost; interrupting assessments")
                self._lost.set()
                return

    def stop(self):
        self._shutdown.set()
        with self._lock:
            executor = self._executor
            self._executor = None
        if self._reconciler:
            self._reconciler.join()
            self._reconciler = None
        if executor is not None:
            # Workers acquire _lock when finishing, so wait outside the lock.
            executor.shutdown(wait=True, cancel_futures=True)
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
        with self._lock:
            self._events.clear()

    def submit(self, assessment_id):
        with self._lock:
            if not self.ready:
                return  # The persisted queued record will be recovered at startup.
            if assessment_id in self._events:
                return
            event = self._events[assessment_id] = Event()
            try:
                self._executor.submit(self._run, assessment_id, event)
            except Exception:
                self._events.pop(assessment_id, None)
                raise

    def cancel(self, assessment_id):
        with self._lock:
            if event := self._events.get(assessment_id):
                event.set()

    def _policy(self, db, assessment):
        project = db.get(models.Project, assessment.project_id)
        target = db.get(models.Target, assessment.target_id)
        validate(project, target, assessment.url)
        require_local_image(target.image)
        try:
            plugins = plugin_registry.select(assessment.plugins)
        except ValueError as exc:
            raise PolicyError(str(exc)) from exc
        return target, plugins

    def _assert_owner(self, db):
        if self._lost.is_set():
            raise Interrupted(_OWNERSHIP_LOST)
        if self._owner_pid is not None and not db.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=:pid AND objid=:key AND granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database()))"
            ),
            {"pid": self._owner_pid, "key": OWNER_LOCK},
        ):
            self._lost.set()
            raise Interrupted(_OWNERSHIP_LOST)

    def _journal_writer(self, assessment_id, attempt_id, token, *, recovery=False):
        def persist(journal, advancing=False):
            with database.SessionLocal() as db:
                item = db.get(models.Assessment, assessment_id, with_for_update=True)
                self._assert_owner(db)
                attempt = latest_attempt(db, assessment_id)
                allowed = (
                    {"recovering", "cancelling", "failed"}
                    if recovery
                    else {"running", "cancelling"}
                )
                if (
                    not item
                    or not attempt
                    or attempt.id != attempt_id
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
                        raise Cancelled(_ASSESSMENT_CANCELLED)
                    if self._shutdown.is_set():
                        raise Interrupted("execution interrupted")
                attempt.operation_journal = deepcopy(journal)
                db.commit()

        return persist

    def _watch_cleanup(self):
        while not self._shutdown.is_set():
            if self._lost.is_set():
                return
            try:
                self.recover(include_failed_cleanup=True)
            except Exception:
                logger.exception("background assessment reconciliation failed")
            if self._shutdown.wait(RECONCILE_INTERVAL_SECONDS):
                return

    def _run(self, assessment_id, cancel_event):
        try:
            if self._shutdown.is_set() or self._lost.is_set():
                return
            with database.SessionLocal() as db:
                item = db.get(models.Assessment, assessment_id, with_for_update=True)
                self._assert_owner(db)
                if not item or item.status != "queued":
                    return
                try:
                    target, plugins = self._policy(db, item)
                    previous = latest_attempt(db, item.id)
                    number = previous.number + 1 if previous else 1
                    if number > MAX_ASSESSMENT_ATTEMPTS:
                        raise PolicyError("crash recovery retry limit reached")
                except (PolicyError, ImageUnavailable, DockerUnavailable) as exc:
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
                context = ExecutionContext(
                    cancel_event,
                    self._shutdown,
                    monotonic() + settings.assessment_timeout_seconds,
                    lambda: not self._lost.is_set(),
                )
                sandbox = sandbox_for(
                    attempt,
                    target,
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
                attempt_id, url = attempt.id, item.url
            outcome = execute(sandbox, url, context, plugins)
            if self._lost.is_set():
                return  # A new owner must reconcile; never overwrite its decisions.
            # The cancellation row lock serializes cancellation against completion.
            with database.SessionLocal() as db:
                item = db.get(models.Assessment, assessment_id, with_for_update=True)
                attempt = latest_attempt(db, assessment_id)
                if (
                    self._lost.is_set()
                    or item.status not in {"running", "cancelling"}
                    or not attempt
                    or attempt.id != attempt_id
                ):
                    return
                self._assert_owner(db)
                if (
                    hasattr(sandbox, "journal")
                    and attempt.operation_journal["owner"] != sandbox.journal["owner"]
                ):
                    return
                if item.status == "cancelling" and outcome.cleanup_verified:
                    outcome.status, outcome.error = "cancelled", _ASSESSMENT_CANCELLED
                finish(db, item, attempt, outcome)
                db.commit()
        except Exception:
            # A later dispatcher startup revisits any nonterminal record left here.
            logger.exception("worker could not finalize assessment %s", assessment_id)
        finally:
            with self._lock:
                self._events.pop(assessment_id, None)

    def recover(self, *, include_failed_cleanup=False):
        """Serialize startup recovery and optional failed-cleanup reconciliation."""
        with self._reconcile_lock:
            self._recover(include_failed_cleanup=include_failed_cleanup)

    def _recover(self, *, include_failed_cleanup):
        recoverable = models.Assessment.status.in_(
            ["running", "recovering", "cancelling"]
        )
        if include_failed_cleanup:
            recoverable = recoverable | (
                (models.Assessment.status == "failed")
                & models.Assessment.cleanup_pending.is_(True)
            )
        with database.SessionLocal() as db:
            ids = list(db.scalars(select(models.Assessment.id).where(recoverable)))
        for assessment_id in ids:
            if self._shutdown.is_set():
                return
            with self._lock:
                if assessment_id in self._events:
                    continue
            if self._lost.is_set():
                raise RuntimeError("dispatcher ownership lost during recovery")
            self._recover_assessment(assessment_id)
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

    def _prepare_recovery(self, db, item):
        """Validate the journal and commit a new owner before cleanup begins."""
        if (
            item.status not in {"running", "recovering", "cancelling"}
            and not item.cleanup_pending
        ):
            return None
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
            return None
        if item.status == "running":
            transition(db, item, "recovering", {"attempt": attempt.number})
        journal = deepcopy(attempt.operation_journal)
        journal["owner"] = str(uuid4())
        attempt.operation_journal = journal
        db.commit()
        return attempt

    def _recover_assessment(self, assessment_id):
        with database.SessionLocal() as db:
            item = db.get(models.Assessment, assessment_id, with_for_update=True)
            self._assert_owner(db)
            original_status = item.status
            attempt = self._prepare_recovery(db, item)
            if attempt is None:
                return
            attempt_id, token = attempt.id, attempt.operation_journal["owner"]
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
                return
            self._finish_recovery(db, item, attempt, cleanup, original_status)
            db.commit()

    def _finish_recovery(self, db, item, attempt, cleanup, original_status):
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
                audit(db, item.project_id, "assessment.cleanup_verified", item.id)
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
            finish(db, item, attempt, Outcome("cancelled", _ASSESSMENT_CANCELLED, True))
        else:
            self._retry_recovered(db, item, attempt)

    def _retry_recovered(self, db, item, attempt):
        try:
            self._policy(db, item)
            if attempt.number >= MAX_ASSESSMENT_ATTEMPTS:
                raise PolicyError("crash recovery retry limit reached")
        except (PolicyError, ImageUnavailable, DockerUnavailable) as exc:
            finish(db, item, attempt, Outcome("failed", str(exc), True))
        else:
            attempt.error = "execution interrupted"
            item.result = None
            transition(db, item, "queued", {"retry_after_attempt": attempt.number})


dispatcher = AssessmentDispatcher()

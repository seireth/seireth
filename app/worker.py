"""Process-local assessment dispatcher with persisted lifecycle state.

The database record is the durable queue entry. A later deployment can replace
the dispatcher with a separate worker process without changing the API
contract.
"""
from concurrent.futures import ThreadPoolExecutor
import logging
from threading import Event, Lock
from concurrent.futures import TimeoutError
from typing import Callable, TypeVar

from . import models
from .config import settings
from .db import SessionLocal
from .orchestrator import run_assessment

logger = logging.getLogger(__name__)
T = TypeVar("T")


class AssessmentWorker:
    """Small cancellable execution primitive used by worker-level tests."""

    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds
        self.cancel_event = Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="seireth-test")

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self, task: Callable[[Event], T], cleanup: Callable[[], None]) -> T:
        future = self._executor.submit(task, self.cancel_event)
        try:
            if self.cancel_event.is_set():
                future.cancel()
            return future.result(timeout=self.timeout_seconds)
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError("assessment timed out") from exc
        finally:
            try:
                cleanup()
            finally:
                self._executor.shutdown(wait=False, cancel_futures=True)


class AssessmentDispatcher:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="seireth")
        self._events: dict[str, Event] = {}
        self._lock = Lock()

    def submit(self, assessment_id: str) -> None:
        with self._lock:
            event = self._events.setdefault(assessment_id, Event())
        self._executor.submit(self._run, assessment_id, event)

    def cancel(self, assessment_id: str) -> None:
        with self._lock:
            event = self._events.get(assessment_id)
            if event:
                event.set()

    def recover(self) -> None:
        with SessionLocal() as db:
            ids = [
                item.id for item in db.query(models.Assessment)
                .filter(models.Assessment.status.in_(("queued", "running")))
                .all()
            ]
        for assessment_id in ids:
            self.submit(assessment_id)

    def _run(self, assessment_id: str, cancel_event: Event) -> None:
        try:
            with SessionLocal() as db:
                assessment = db.get(models.Assessment, assessment_id)
                if not assessment or assessment.status == "cancelled" or cancel_event.is_set():
                    return
                target = db.get(models.Target, assessment.target_id)
                scope = db.get(models.AuthorizationScope, assessment.scope_id)
                if not target or not scope:
                    assessment.status = "failed"
                    assessment.result = {"error": "assessment resources are unavailable"}
                    db.commit()
                    return
                try:
                    run_assessment(
                        db, assessment, scope.allowed_url, target.image, target.name,
                        cancel_event=cancel_event,
                    )
                except Exception:
                    logger.exception("assessment worker failed", extra={"assessment_id": assessment_id})
                    assessment.status = "failed"
                    assessment.result = {
                        "sandbox_backend": settings.sandbox_backend,
                        "cleanup_verified": False,
                        "error": "assessment execution failed",
                    }
                if cancel_event.is_set() and assessment.status != "cancelled":
                    assessment.status = "cancelled"
                    assessment.result = {
                        "sandbox_backend": settings.sandbox_backend,
                        "cleanup_verified": bool(
                            assessment.result and assessment.result.get("cleanup_verified")
                        ),
                        "error": "assessment cancelled",
                    }
                    db.add(models.AuditEvent(
                        project_id=assessment.project_id,
                        action="assessment.cancelled",
                        resource_id=assessment.id,
                    ))
                else:
                    db.add(models.AuditEvent(
                        project_id=assessment.project_id,
                        action=f"assessment.{assessment.status}",
                        resource_id=assessment.id,
                    ))
                db.commit()
        finally:
            with self._lock:
                self._events.pop(assessment_id, None)


dispatcher = AssessmentDispatcher()

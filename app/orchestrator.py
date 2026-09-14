from datetime import datetime, timezone
import logging
from threading import Event
from urllib.parse import urlsplit
from .models import Assessment, Evidence, Finding
from .plugins import security_headers
from .config import settings
from .sandbox import DockerSandbox, InMemorySandbox

logger = logging.getLogger(__name__)

def run_assessment(db, assessment: Assessment, target_url: str, target_image: str,
                   target_label: str = "target",
                   cancel_event: Event | None = None) -> None:
    """Execute the MVP passive plugin and persist its findings and cleanup result.

    Args:
        db: SQLAlchemy session used to persist assessment records.
        assessment: Assessment record being executed.
        target_url: URL authorized by the assessment scope.
    """

    assessment.status = "running"
    if settings.sandbox_backend == "docker":
        sandbox = DockerSandbox(
            target_image, runner_image=settings.docker_runner_image,
            memory=settings.docker_memory, cpus=settings.docker_cpus,
            pids_limit=settings.docker_pids_limit,
            target_host=urlsplit(target_url).hostname,
            target_label=target_label,
            assessment_id=assessment.id,
            command_timeout=settings.docker_timeout_seconds,
        )
    elif settings.sandbox_backend == "inmemory":
        sandbox = InMemorySandbox()
    else:
        raise ValueError(f"unsupported sandbox backend: {settings.sandbox_backend}")
    findings = None
    error: Exception | None = None
    try:
        if cancel_event and cancel_event.is_set():
            assessment.status = "cancelled"
            return
        findings = security_headers(sandbox, target_url)
        for item in findings:
            db.add(Finding(assessment_id=assessment.id, plugin="security-headers",
                           title=item.title, severity=item.severity,
                           description=item.description))
            db.add(Evidence(assessment_id=assessment.id, kind="http-response", data=item.evidence))
    except Exception as exc:
        logger.exception("assessment plugin execution failed", extra={"assessment_id": assessment.id})
        error = exc
    finally:
        cleanup = sandbox.cleanup()
    if cancel_event and cancel_event.is_set():
        assessment.status = "cancelled"
        assessment.result = {
            "sandbox_backend": sandbox.backend_name,
            "cleanup_verified": cleanup,
            "error": "assessment cancelled",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    elif error is not None:
        assessment.result = {"sandbox_backend": sandbox.backend_name,
                             "cleanup_verified": cleanup,
                             "error": "assessment execution failed",
                             "completed_at": datetime.now(timezone.utc).isoformat()}
        assessment.status = "failed"
    else:
        assessment.result = {"plugin": "security-headers", "finding_count": len(findings or []),
                             "sandbox_backend": sandbox.backend_name,
                             "cleanup_verified": cleanup,
                             "completed_at": datetime.now(timezone.utc).isoformat()}
        assessment.status = "completed" if cleanup else "failed"
"""Assessment execution orchestration."""

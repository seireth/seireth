from datetime import datetime, timezone
from urllib.parse import urlsplit
from .models import Assessment, Evidence, Finding
from .plugins import security_headers
from .config import settings
from .sandbox import DockerSandbox, InMemorySandbox


def run_assessment(db, assessment: Assessment, target_url: str, target_image: str,
                   target_owned_demo: bool = False) -> None:
    """Execute the MVP passive plugin and persist its findings and cleanup result.

    Args:
        db: SQLAlchemy session used to persist assessment records.
        assessment: Assessment record being executed.
        target_url: URL authorized by the assessment scope.
    """

    assessment.status = "running"
    if settings.sandbox_backend == "docker":
        if not target_owned_demo:
            raise ValueError("Docker execution is restricted to owned demo targets")
        sandbox = DockerSandbox(
            target_image, runner_image=settings.docker_runner_image,
            memory=settings.docker_memory, cpus=settings.docker_cpus,
            pids_limit=settings.docker_pids_limit,
            target_host=urlsplit(target_url).hostname,
            command_timeout=settings.docker_timeout_seconds,
        )
    elif settings.sandbox_backend == "inmemory":
        sandbox = InMemorySandbox()
    else:
        raise ValueError(f"unsupported sandbox backend: {settings.sandbox_backend}")
    findings = None
    error: Exception | None = None
    try:
        findings = security_headers(sandbox, target_url)
        for item in findings:
            db.add(Finding(assessment_id=assessment.id, plugin="security-headers",
                           title=item.title, severity=item.severity,
                           description=item.description))
            db.add(Evidence(assessment_id=assessment.id, kind="http-response", data=item.evidence))
    except Exception as exc:
        error = exc
    finally:
        cleanup = sandbox.cleanup()
    if error is not None:
        assessment.result = {"sandbox_backend": sandbox.backend_name,
                             "cleanup_verified": cleanup,
                             "error": str(error),
                             "completed_at": datetime.now(timezone.utc).isoformat()}
        assessment.status = "failed"
    else:
        assessment.result = {"plugin": "security-headers", "finding_count": len(findings or []),
                             "sandbox_backend": sandbox.backend_name,
                             "cleanup_verified": cleanup,
                             "completed_at": datetime.now(timezone.utc).isoformat()}
        assessment.status = "completed" if cleanup else "failed"
"""Assessment execution orchestration."""

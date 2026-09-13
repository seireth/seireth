from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session
from urllib.parse import urlsplit
from . import models
from .auth import require_auth
from .config import settings
from .db import Base, engine, get_db
from .orchestrator import run_assessment
from .schemas import AssessmentCreate, AssessmentOut, ProjectCreate, ScopeCreate, TargetCreate

Base.metadata.create_all(engine)
app = FastAPI(title="Seireth MVP-0", version="0.1.0")


def unexpired(value: datetime) -> bool:
    """Return whether a timestamp is in the future, treating naive values as UTC."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value > datetime.now(timezone.utc)

def bounded_url(candidate: str, registered: str) -> bool:
    """Return whether a candidate URL stays within the registered target origin/path."""

    left, right = urlsplit(candidate), urlsplit(registered)
    left_port = left.port or (443 if left.scheme == "https" else 80)
    right_port = right.port or (443 if right.scheme == "https" else 80)
    return (left.scheme, left.hostname, left_port) == (right.scheme, right.hostname, right_port) and (
        right.path == left.path or right.path.startswith(left.path.rstrip("/") + "/"))


def audit(db: Session, project_id: str, action: str, resource_id: str) -> None:
    """Queue an append-only audit event for the current database transaction."""

    db.add(models.AuditEvent(project_id=project_id, action=action, resource_id=resource_id))


@app.get("/health")
def health() -> dict[str, str]:
    """Return a lightweight readiness response."""

    return {"status": "ok"}


@app.post("/api/v1/projects", dependencies=[Depends(require_auth)])
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    """Create a project and record its creation in the audit log."""

    item = models.Project(name=payload.name)
    db.add(item); db.flush(); audit(db, item.id, "project.created", item.id); db.commit()
    return {"id": item.id, "name": item.name}


@app.post("/api/v1/targets", dependencies=[Depends(require_auth)])
def create_target(payload: TargetCreate, db: Session = Depends(get_db)):
    """Register a target that belongs to an existing project."""

    if db.get(models.Project, payload.project_id) is None:
        raise HTTPException(404, "project not found")
    item = models.Target(project_id=payload.project_id, name=payload.name, image=payload.image,
                         url=str(payload.url), owned_demo=payload.owned_demo)
    db.add(item); db.flush(); audit(db, item.project_id, "target.registered", item.id); db.commit()
    return {"id": item.id, "url": item.url}


@app.post("/api/v1/authorization-scopes", dependencies=[Depends(require_auth)])
def create_scope(payload: ScopeCreate, db: Session = Depends(get_db)):
    """Create an unexpired authorization scope bounded to its target."""

    target = db.get(models.Target, payload.target_id)
    if not target or target.project_id != payload.project_id or not unexpired(payload.expires_at):
        raise HTTPException(400, "invalid or expired authorization scope")
    if not bounded_url(str(payload.allowed_url), target.url):
        raise HTTPException(400, "scope must be bounded to the registered target")
    item = models.AuthorizationScope(project_id=payload.project_id, target_id=payload.target_id,
                                     allowed_url=str(payload.allowed_url), expires_at=payload.expires_at)
    db.add(item); db.flush(); audit(db, item.project_id, "scope.authorized", item.id); db.commit()
    return {"id": item.id}


@app.post("/api/v1/assessments", response_model=AssessmentOut, dependencies=[Depends(require_auth)])
def create_assessment(payload: AssessmentCreate, db: Session = Depends(get_db)):
    """Validate authorization and synchronously execute a passive assessment."""

    target = db.get(models.Target, payload.target_id)
    scope = db.get(models.AuthorizationScope, payload.scope_id)
    if (not target or target.project_id != payload.project_id or not scope or
            scope.project_id != payload.project_id or scope.target_id != target.id or
            not unexpired(scope.expires_at)):
        raise HTTPException(403, "valid authorization scope required")
    if payload.profile != "passive":
        raise HTTPException(400, "MVP-0 only supports the passive profile")
    if settings.sandbox_backend == "docker" and not target.owned_demo:
        raise HTTPException(403, "Docker execution is restricted to owned demo targets")
    item = models.Assessment(project_id=payload.project_id, target_id=target.id,
                             scope_id=scope.id, profile=payload.profile)
    db.add(item); db.flush(); audit(db, item.project_id, "assessment.queued", item.id)
    run_assessment(db, item, scope.allowed_url, target.image, target.owned_demo)
    audit(db, item.project_id, f"assessment.{item.status}", item.id); db.commit()
    return item


@app.get("/api/v1/assessments/{assessment_id}", response_model=AssessmentOut,
         dependencies=[Depends(require_auth)])
def get_assessment(assessment_id: str, db: Session = Depends(get_db)):
    """Return the persisted state of one assessment."""

    item = db.get(models.Assessment, assessment_id)
    if not item:
        raise HTTPException(404, "assessment not found")
    return item


@app.get("/api/v1/assessments/{assessment_id}/results", dependencies=[Depends(require_auth)])
def get_results(assessment_id: str, db: Session = Depends(get_db)):
    """Return the assessment status, JSON result, and normalized findings."""

    item = db.get(models.Assessment, assessment_id)
    if not item:
        raise HTTPException(404, "assessment not found")
    return {"assessment_id": item.id, "status": item.status, "result": item.result,
            "findings": [{"id": f.id, "plugin": f.plugin, "title": f.title,
                          "severity": f.severity, "description": f.description} for f in item.findings]}


@app.get("/api/v1/projects/{project_id}/audit-events",
         dependencies=[Depends(require_auth)])
def get_audit_events(project_id: str, db: Session = Depends(get_db)):
    """Return the audit trail for a project in chronological order."""

    if db.get(models.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    events = (
        db.query(models.AuditEvent)
        .filter(models.AuditEvent.project_id == project_id)
        .order_by(models.AuditEvent.created_at, models.AuditEvent.id)
        .all()
    )
    return [
        {
            "id": event.id,
            "action": event.action,
            "resource_id": event.resource_id,
            "details": event.details,
            "created_at": event.created_at,
        }
        for event in events
    ]


@app.post("/api/v1/assessments/{assessment_id}/cancel",
          dependencies=[Depends(require_auth)])
def cancel_assessment(assessment_id: str, db: Session = Depends(get_db)):
    """Cancel an assessment that has not reached a terminal state."""

    item = db.get(models.Assessment, assessment_id)
    if not item:
        raise HTTPException(404, "assessment not found")
    if item.status not in ("queued", "running"):
        raise HTTPException(409, "assessment is no longer cancellable")
    item.status = "cancelled"
    audit(db, item.project_id, "assessment.cancelled", item.id)
    db.commit()
    return {"id": item.id, "status": item.status}
"""FastAPI application and MVP-0 assessment endpoints."""

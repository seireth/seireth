from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .db import get_db
from .lifecycle import audit, transition
from .migration import check_schema
from .policy import ACTOR as MVP_ACTOR
from .policy import PolicyError, bounded_url, unexpired, validate
from .schemas import (
    AssessmentCreate,
    AssessmentOut,
    ProjectCreate,
    ScopeCreate,
    TargetCreate,
)
from .worker import dispatcher


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Check schema and hold dispatcher ownership for the application lifetime."""
    check_schema()
    dispatcher.start()
    try:
        yield
    finally:
        dispatcher.stop()


app = FastAPI(title="Seireth MVP-0", version="0.1.0", lifespan=lifespan)


def authorize_project(db: Session, project_id: str) -> models.Project:
    project = db.get(models.Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    if project.owner_actor != MVP_ACTOR:
        raise HTTPException(403, "project access denied")
    return project


@app.get("/health")
def health() -> dict[str, str]:
    """Return a lightweight readiness response."""

    if not dispatcher.ready:
        raise HTTPException(503, "assessment dispatcher unavailable")
    return {"status": "ok"}


@app.post("/api/v1/projects")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    """Create a project and record its creation in the audit log."""

    item = models.Project(name=payload.name, owner_actor=MVP_ACTOR)
    db.add(item)
    db.flush()
    audit(db, item.id, "project.created", item.id)
    db.commit()
    return {"id": item.id, "name": item.name}


@app.post("/api/v1/targets")
def create_target(payload: TargetCreate, db: Session = Depends(get_db)):
    """Register a target that belongs to an existing project."""

    authorize_project(db, payload.project_id)
    target_url = str(payload.url)
    target_image = payload.image or settings.docker_target_image
    if target_image not in settings.docker_allowed_target_images:
        raise HTTPException(400, "target image is not in the trusted image allowlist")
    item = models.Target(
        project_id=payload.project_id,
        name=payload.name,
        image=target_image,
        url=target_url,
    )
    db.add(item)
    db.flush()
    audit(db, item.project_id, "target.registered", item.id)
    db.commit()
    return {"id": item.id, "url": item.url}


@app.post("/api/v1/authorization-scopes")
def create_scope(payload: ScopeCreate, db: Session = Depends(get_db)):
    """Create an unexpired authorization scope bounded to its target."""

    authorize_project(db, payload.project_id)
    target = db.get(models.Target, payload.target_id)
    if (
        not target
        or target.project_id != payload.project_id
        or not unexpired(payload.expires_at)
    ):
        raise HTTPException(400, "invalid or expired authorization scope")
    if not bounded_url(str(payload.allowed_url), target.url):
        raise HTTPException(400, "scope must be bounded to the registered target")
    item = models.AuthorizationScope(
        project_id=payload.project_id,
        target_id=payload.target_id,
        allowed_url=str(payload.allowed_url),
        expires_at=payload.expires_at,
    )
    db.add(item)
    db.flush()
    audit(db, item.project_id, "scope.authorized", item.id)
    db.commit()
    return {"id": item.id}


@app.post("/api/v1/assessments", response_model=AssessmentOut, status_code=202)
def create_assessment(
    payload: AssessmentCreate, response: Response, db: Session = Depends(get_db)
):
    """Validate authorization and enqueue a passive assessment."""

    project = authorize_project(db, payload.project_id)
    target = db.get(models.Target, payload.target_id)
    scope = db.get(models.AuthorizationScope, payload.scope_id)
    if payload.profile != "passive":
        raise HTTPException(400, "MVP-0 only supports the passive profile")
    try:
        validate(
            project,
            target,
            scope,
            payload.profile,
            settings.docker_allowed_target_images,
        )
    except PolicyError as exc:
        raise HTTPException(403, str(exc)) from exc
    item = models.Assessment(
        project_id=payload.project_id,
        target_id=target.id,
        scope_id=scope.id,
        profile=payload.profile,
    )
    db.add(item)
    db.flush()
    audit(db, item.project_id, "assessment.queued", item.id)
    db.commit()
    response.headers["Location"] = f"/api/v1/assessments/{item.id}"
    dispatcher.submit(item.id)
    return item


@app.get("/api/v1/assessments/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: str, db: Session = Depends(get_db)):
    """Return the persisted state of one assessment."""

    item = db.get(models.Assessment, assessment_id)
    if not item:
        raise HTTPException(404, "assessment not found")
    authorize_project(db, item.project_id)
    return item


@app.get("/api/v1/assessments/{assessment_id}/results")
def get_results(assessment_id: str, db: Session = Depends(get_db)):
    """Return the assessment status, JSON result, and normalized findings."""

    item = db.get(models.Assessment, assessment_id)
    if not item:
        raise HTTPException(404, "assessment not found")
    authorize_project(db, item.project_id)
    return {
        "assessment_id": item.id,
        "status": item.status,
        "result": item.result,
        "findings": [
            {
                "id": f.id,
                "plugin": f.plugin,
                "title": f.title,
                "severity": f.severity,
                "description": f.description,
            }
            for f in item.findings
        ],
    }


@app.get("/api/v1/projects/{project_id}/audit-events")
def get_audit_events(project_id: str, db: Session = Depends(get_db)):
    """Return the audit trail for a project in chronological order."""

    authorize_project(db, project_id)
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


@app.post("/api/v1/assessments/{assessment_id}/cancel")
def cancel_assessment(
    assessment_id: str, response: Response, db: Session = Depends(get_db)
):
    item = db.scalar(
        select(models.Assessment)
        .where(models.Assessment.id == assessment_id)
        .with_for_update()
    )
    if not item:
        raise HTTPException(404, "assessment not found")
    authorize_project(db, item.project_id)
    if item.status not in ("queued", "running", "recovering", "cancelling"):
        raise HTTPException(409, "assessment is no longer cancellable")
    if item.status == "queued":
        transition(db, item, "cancelled")
    else:
        if item.status != "cancelling":
            transition(db, item, "cancelling")
        response.status_code = 202
    db.commit()
    dispatcher.cancel(item.id)
    return {"id": item.id, "status": item.status}

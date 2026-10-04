from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..lifecycle import audit
from ..policy import ACTOR as MVP_ACTOR
from ..schemas import (
    PageOut,
    ProjectCreate,
    ProjectOut,
)
from .dependencies import authorize_project, page, pagination

router = APIRouter()


@router.get("/api/v1/projects", response_model=PageOut[ProjectOut])
def list_projects(db: Session = Depends(get_db), bounds=Depends(pagination)):
    return page(
        db,
        select(models.Project)
        .where(models.Project.owner_actor == MVP_ACTOR)
        .order_by(models.Project.created_at.desc(), models.Project.id),
        bounds,
    )


@router.get("/api/v1/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    return authorize_project(db, project_id)


@router.post("/api/v1/projects")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    """Create a project and record its creation in the audit log."""

    item = models.Project(name=payload.name, owner_actor=MVP_ACTOR)
    db.add(item)
    db.flush()
    audit(db, item.id, "project.created", item.id)
    db.commit()
    return {"id": item.id, "name": item.name}


@router.get("/api/v1/projects/{project_id}/audit-events")
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

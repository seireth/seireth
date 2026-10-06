from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..assessments.lifecycle import audit
from ..core.identity import ACTOR
from ..persistence import models
from ..persistence.db import get_db
from .dependencies import authorize_project, page, pagination
from .schemas import PageOut, ProjectCreate, ProjectOut

router = APIRouter()


@router.get("/projects", response_model=PageOut[ProjectOut])
def list_projects(db: Session = Depends(get_db), bounds=Depends(pagination)):
    return page(
        db,
        select(models.Project)
        .where(models.Project.owner_actor == ACTOR)
        .order_by(models.Project.created_at.desc(), models.Project.id),
        bounds,
    )


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    return authorize_project(db, project_id)


@router.post("/projects")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    """Create a project and record its creation in the audit log."""

    item = models.Project(name=payload.name, owner_actor=ACTOR)
    db.add(item)
    db.flush()
    audit(db, item.id, "project.created", item.id)
    db.commit()
    return {"id": item.id, "name": item.name}


@router.get("/projects/{project_id}/audit-events")
def get_audit_events(project_id: str, db: Session = Depends(get_db)):
    """Return the audit trail for a project in chronological order."""

    authorize_project(db, project_id)
    events = db.scalars(
        select(models.AuditEvent)
        .where(models.AuditEvent.project_id == project_id)
        .order_by(models.AuditEvent.created_at, models.AuditEvent.id)
    ).all()
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

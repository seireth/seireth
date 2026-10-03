from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..db import get_db
from ..lifecycle import audit
from ..schemas import (
    PageOut,
    TargetCreate,
    TargetOut,
)
from .dependencies import authorize_project, page, pagination

router = APIRouter()


@router.get("/api/v1/projects/{project_id}/targets", response_model=PageOut[TargetOut])
def list_targets(
    project_id: str, db: Session = Depends(get_db), bounds=Depends(pagination)
):
    authorize_project(db, project_id)
    return page(
        db,
        select(models.Target)
        .where(models.Target.project_id == project_id)
        .order_by(models.Target.id),
        bounds,
    )


@router.get("/api/v1/targets/{target_id}", response_model=TargetOut)
def get_target(target_id: str, db: Session = Depends(get_db)):
    item = db.get(models.Target, target_id)
    if item is None:
        raise HTTPException(404, "target not found")
    authorize_project(db, item.project_id)
    return item


@router.post("/api/v1/targets")
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

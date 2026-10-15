from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..assessments import images
from ..assessments.lifecycle import audit
from ..assessments.policy import PolicyError, bounded_url
from ..assessments.profiles import load_config
from ..persistence import models
from ..persistence.db import get_db
from .dependencies import authorize_project, page, pagination
from .schemas import PageOut, TargetCreate, TargetImagesOut, TargetOut

router = APIRouter()


@router.get(
    "/target-images",
    response_model=TargetImagesOut,
    responses={503: {"description": "Docker image discovery unavailable"}},
)
def target_images():
    try:
        return {"items": images.local_images()}
    except images.DockerUnavailable as exc:
        raise HTTPException(503, str(exc)) from None


@router.get("/projects/{project_id}/targets", response_model=PageOut[TargetOut])
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


@router.get(
    "/targets/{target_id}",
    response_model=TargetOut,
    responses={404: {"description": "Target not found"}},
)
def get_target(target_id: str, db: Session = Depends(get_db)):
    item = db.get(models.Target, target_id)
    if item is None:
        raise HTTPException(404, "target not found")
    authorize_project(db, item.project_id)
    return item


@router.post(
    "/targets",
    response_model=TargetOut,
    responses={
        400: {"description": "Target URL or local image is unavailable"},
        503: {
            "description": "Docker image inspection or operator configuration unavailable"
        },
    },
)
def create_target(payload: TargetCreate, db: Session = Depends(get_db)):
    """Register a target that belongs to an existing project."""

    authorize_project(db, payload.project_id)
    target_url = str(payload.url)
    target_image = payload.image
    if not bounded_url(target_url, target_url):
        raise HTTPException(400, "invalid target URL boundary")
    if payload.launch_profile or payload.network_profile or payload.trust_profile:
        try:
            config = load_config()
        except PolicyError as exc:
            raise HTTPException(503, str(exc)) from None
        for name, entries in (
            (payload.launch_profile, config.launches),
            (payload.network_profile, config.networks),
            (payload.trust_profile, config.trusts),
        ):
            if name and name not in entries:
                raise HTTPException(400, "selected operator profile is unavailable")
    try:
        if payload.kind == "docker":
            images.require_local_image(target_image)
    except images.ImageUnavailable as exc:
        raise HTTPException(400, str(exc)) from None
    except images.DockerUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    item = models.Target(
        project_id=payload.project_id,
        name=payload.name,
        image=target_image,
        url=target_url,
        kind=payload.kind,
        launch_profile=payload.launch_profile,
        network_profile=payload.network_profile,
        trust_profile=payload.trust_profile,
    )
    db.add(item)
    db.flush()
    audit(db, item.project_id, "target.registered", item.id)
    db.commit()
    return item

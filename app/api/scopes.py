from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..assessments.lifecycle import audit
from ..assessments.policy import bounded_url, unexpired
from ..persistence import models
from ..persistence.db import get_db
from .dependencies import authorize_project, page, pagination
from .schemas import PageOut, ScopeCreate, ScopeOut

router = APIRouter()


@router.get(
    "/projects/{project_id}/authorization-scopes",
    response_model=PageOut[ScopeOut],
    responses={404: {"description": "Project or target not found in project"}},
)
def list_scopes(
    project_id: str,
    target_id: str | None = None,
    db: Session = Depends(get_db),
    bounds=Depends(pagination),
):
    authorize_project(db, project_id)
    query = select(models.AuthorizationScope).where(
        models.AuthorizationScope.project_id == project_id
    )
    if target_id is not None:
        target = db.get(models.Target, target_id)
        if target is None or target.project_id != project_id:
            raise HTTPException(404, "target not found in project")
        query = query.where(models.AuthorizationScope.target_id == target_id)
    return page(
        db,
        query.order_by(
            models.AuthorizationScope.expires_at.desc(), models.AuthorizationScope.id
        ),
        bounds,
    )


@router.get(
    "/authorization-scopes/{scope_id}",
    response_model=ScopeOut,
    responses={404: {"description": "Authorization scope not found"}},
)
def get_scope(scope_id: str, db: Session = Depends(get_db)):
    item = db.get(models.AuthorizationScope, scope_id)
    if item is None:
        raise HTTPException(404, "authorization scope not found")
    authorize_project(db, item.project_id)
    return item


@router.post(
    "/authorization-scopes",
    responses={
        400: {
            "description": "Authorization scope is invalid, expired, or outside the target URL boundary"
        }
    },
)
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

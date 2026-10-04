import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..db import get_db
from ..lifecycle import audit, transition
from ..plugins import registry as plugin_registry
from ..policy import PolicyError, validate
from ..schemas import (
    AssessmentCreate,
    AssessmentEvidenceOut,
    AssessmentOut,
    AssessmentResultsOut,
    EvidenceOut,
    PageOut,
)
from ..worker import dispatcher
from .dependencies import authorize_project, page, pagination

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/api/v1/projects/{project_id}/assessments", response_model=PageOut[AssessmentOut]
)
def list_assessments(
    project_id: str, db: Session = Depends(get_db), bounds=Depends(pagination)
):
    authorize_project(db, project_id)
    return page(
        db,
        select(models.Assessment)
        .where(models.Assessment.project_id == project_id)
        .order_by(models.Assessment.created_at.desc(), models.Assessment.id),
        bounds,
    )


@router.post("/api/v1/assessments", response_model=AssessmentOut, status_code=202)
def create_assessment(
    payload: AssessmentCreate, response: Response, db: Session = Depends(get_db)
):
    """Validate authorization and enqueue a passive assessment."""

    project = authorize_project(db, payload.project_id)
    target = db.get(models.Target, payload.target_id)
    scope = db.get(models.AuthorizationScope, payload.scope_id)
    try:
        plugins = plugin_registry.select(payload.plugins)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        validate(
            project,
            target,
            scope,
            settings.docker_allowed_target_images,
        )
    except PolicyError as exc:
        raise HTTPException(403, str(exc)) from exc
    item = models.Assessment(
        project_id=payload.project_id,
        target_id=target.id,
        scope_id=scope.id,
        plugins=[plugin.manifest.id for plugin in plugins],
    )
    db.add(item)
    db.flush()
    audit(db, item.project_id, "assessment.queued", item.id)
    db.commit()
    response.headers["Location"] = f"/api/v1/assessments/{item.id}"
    dispatcher.submit(item.id)
    return item


@router.get("/api/v1/assessments/{assessment_id}", response_model=AssessmentOut)
def get_assessment(assessment_id: str, db: Session = Depends(get_db)):
    """Return the persisted state of one assessment."""

    item = db.get(models.Assessment, assessment_id)
    if not item:
        raise HTTPException(404, "assessment not found")
    authorize_project(db, item.project_id)
    return item


@router.get(
    "/api/v1/assessments/{assessment_id}/results", response_model=AssessmentResultsOut
)
def get_results(assessment_id: str, db: Session = Depends(get_db)):
    """Return the assessment status, JSON result, and normalized findings."""

    item = get_assessment(assessment_id, db)
    return {
        "assessment_id": item.id,
        "status": item.status,
        "cleanup_pending": item.cleanup_pending,
        "result": item.result,
        "findings": item.findings,
    }


@router.get(
    "/api/v1/assessments/{assessment_id}/evidence",
    response_model=AssessmentEvidenceOut,
)
def get_evidence(assessment_id: str, db: Session = Depends(get_db)):
    """Return validated evidence for an authorized, completed assessment."""
    item = get_assessment(assessment_id, db)
    evidence = []
    if item.status == models.AssessmentStatus.completed:
        rows = db.scalars(
            select(models.Evidence)
            .join(models.Finding)
            .where(models.Finding.assessment_id == item.id)
            .order_by(models.Evidence.id)
        )
        for row in rows:
            try:
                evidence.append(
                    EvidenceOut(
                        id=row.id,
                        finding_id=row.finding_id,
                        kind=row.kind,
                        data=row.data,
                    )
                )
            except ValidationError:
                logger.error(
                    "Invalid stored evidence for assessment %s, evidence %s",
                    item.id,
                    row.id,
                )
                raise HTTPException(500, "stored evidence is invalid") from None
    return AssessmentEvidenceOut(
        assessment_id=item.id,
        status=item.status,
        cleanup_pending=item.cleanup_pending,
        evidence=evidence,
    )


@router.post("/api/v1/assessments/{assessment_id}/cancel")
def cancel_assessment(
    assessment_id: str, response: Response, db: Session = Depends(get_db)
):
    item = db.get(models.Assessment, assessment_id, with_for_update=True)
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

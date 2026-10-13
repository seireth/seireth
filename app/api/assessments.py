import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..assessments import images
from ..assessments.lifecycle import attempt_result, audit, latest_attempt, transition
from ..assessments.plans import RoutePlan, freeze_plan
from ..assessments.policy import PolicyError
from ..assessments.worker import dispatcher
from ..assessments.workflows import public_findings, refresh_result
from ..core.config import settings
from ..persistence import models
from ..persistence.db import get_db
from .dependencies import authorize_project, page, pagination
from .schemas import (
    AssessmentCreate,
    AssessmentEvidenceOut,
    AssessmentOut,
    AssessmentReportOut,
    AssessmentResultsOut,
    EvidenceOut,
    PageOut,
    ReportAssessmentOut,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_ASSESSMENT_NOT_FOUND_RESPONSE = {"description": "Assessment not found"}


def load_assessment(
    db: Session, assessment_id: str
) -> tuple[models.Assessment, models.Project]:
    item = db.get(models.Assessment, assessment_id)
    if not item:
        raise HTTPException(404, "assessment not found")
    project = authorize_project(db, item.project_id)
    return item, project


def load_evidence(db: Session, item: models.Assessment) -> list[EvidenceOut]:
    evidence = []
    findings = public_findings(db, item)
    if findings:
        rows = db.scalars(
            select(models.Evidence)
            .join(models.Finding)
            .where(models.Finding.id.in_([finding.id for finding in findings]))
            .order_by(models.Evidence.id)
        )
        for row in rows:
            try:
                evidence.append(EvidenceOut.model_validate(row, from_attributes=True))
            except ValidationError:
                logger.error(
                    "Invalid stored evidence for assessment %s, evidence %s",
                    item.id,
                    row.id,
                )
                raise HTTPException(500, "stored evidence is invalid") from None
    return evidence


@router.get("/projects/{project_id}/assessments", response_model=PageOut[AssessmentOut])
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


@router.post(
    "/assessments",
    response_model=AssessmentOut,
    status_code=202,
    responses={
        400: {
            "description": "Plugin selection is invalid or image is unavailable locally"
        },
        403: {"description": "Project access or target boundary is denied"},
        503: {"description": "Docker image inspection unavailable"},
    },
)
def create_assessment(
    payload: AssessmentCreate,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    """Validate the target, response URL, and plugins before enqueueing."""

    project = authorize_project(db, payload.project_id)
    target = db.get(models.Target, payload.target_id)
    try:
        if not target:
            raise PolicyError("valid project and target required")
        if target.project_id != project.id:
            raise PolicyError("target does not belong to this project")
        routes = (
            payload.routes
            if payload.routes is not None
            else [RoutePlan(key="response", url=payload.url, plugins=payload.plugins)]
        )
        snapshot = freeze_plan(
            project,
            target,
            routes,
            timeout_seconds=settings.assessment_timeout_seconds
            if payload.routes is None
            else None,
            baseline=payload.baseline,
            control_endpoint=request.scope.get("server"),
        )
    except PolicyError as exc:
        raise HTTPException(403, str(exc)) from exc
    except images.ImageUnavailable as exc:
        raise HTTPException(400, str(exc)) from None
    except images.DockerUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except ValueError:
        raise HTTPException(400, "invalid plugin selection or plan") from None
    if payload.baseline:
        baseline, _ = load_assessment(db, payload.baseline)
        if baseline.project_id != project.id:
            raise HTTPException(403, "baseline must belong to this project")
    item = models.Assessment(
        project_id=payload.project_id,
        target_id=target.id,
        plan_snapshot=snapshot,
    )
    db.add(item)
    db.flush()
    audit(db, item.project_id, "assessment.queued", item.id)
    db.commit()
    response.headers["Location"] = f"/api/v1/assessments/{item.id}"
    dispatcher.submit(item.id)
    return item


@router.get(
    "/assessments/{assessment_id}",
    response_model=AssessmentOut,
    responses={404: _ASSESSMENT_NOT_FOUND_RESPONSE},
)
def get_assessment(assessment_id: str, db: Session = Depends(get_db)):
    """Return the persisted state of one assessment."""

    item, _ = load_assessment(db, assessment_id)
    return item


@router.get(
    "/assessments/{assessment_id}/results",
    response_model=AssessmentResultsOut,
    responses={404: _ASSESSMENT_NOT_FOUND_RESPONSE},
)
def get_results(assessment_id: str, db: Session = Depends(get_db)):
    """Return the assessment status, JSON result, and normalized findings."""

    item, _ = load_assessment(db, assessment_id)
    return {
        "assessment_id": item.id,
        "status": item.status,
        "cleanup_pending": item.cleanup_pending,
        "result": item.result,
        "findings": public_findings(db, item),
    }


@router.get(
    "/assessments/{assessment_id}/evidence",
    response_model=AssessmentEvidenceOut,
    responses={
        404: _ASSESSMENT_NOT_FOUND_RESPONSE,
        500: {"description": "Stored evidence is invalid"},
    },
)
def get_evidence(assessment_id: str, db: Session = Depends(get_db)):
    """Return validated evidence for an authorized, completed assessment."""
    item, _ = load_assessment(db, assessment_id)
    return AssessmentEvidenceOut(
        assessment_id=item.id,
        status=item.status,
        cleanup_pending=item.cleanup_pending,
        evidence=load_evidence(db, item),
    )


@router.get(
    "/assessments/{assessment_id}/report",
    response_model=AssessmentReportOut,
    response_model_exclude_unset=True,
    responses={
        404: _ASSESSMENT_NOT_FOUND_RESPONSE,
        409: {"description": "Assessment is not finished"},
        500: {"description": "Stored report data or evidence is invalid"},
    },
)
def get_report(assessment_id: str, response: Response, db: Session = Depends(get_db)):
    """Assemble a current, read-only snapshot from documented public fields."""
    item, project = load_assessment(db, assessment_id)
    if item.status not in {"completed", "failed", "cancelled"}:
        raise HTTPException(409, "assessment is not finished")
    # Capture scalar state once; cleanup reconciliation can update future reports.
    try:
        assessment = ReportAssessmentOut.model_validate(item)
        report = AssessmentReportOut(
            schema_version=1,
            generated_at=models.now(),
            project=project,
            target=item.plan_snapshot["target"],
            assessment=assessment,
            findings=public_findings(db, item),
            evidence=load_evidence(db, item),
        )
    except ValidationError:
        logger.error("Invalid stored report data for assessment %s", item.id)
        raise HTTPException(500, "stored report data is invalid") from None
    response.headers["Cache-Control"] = "no-store"
    return report


@router.post(
    "/assessments/{assessment_id}/cancel",
    responses={
        404: _ASSESSMENT_NOT_FOUND_RESPONSE,
        409: {"description": "Assessment is no longer cancellable"},
    },
)
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
        attempt = latest_attempt(db, item.id)
        item.result = {
            "error": "assessment cancelled before execution",
            "execution_outcome": "not_started",
            "cleanup_verified": True,
            "cleanup_reason": None,
            "completed_at": models.now().isoformat(),
        }
        if attempt:
            item.result = {
                **item.result,
                **attempt_result(attempt),
                "cleanup_verified": attempt.cleanup_verified,
            }
            item.cleanup_pending = not attempt.cleanup_verified
        refresh_result(db, item, attempt)
    else:
        if item.status != "cancelling":
            transition(db, item, "cancelling")
        response.status_code = 202
    db.commit()
    dispatcher.cancel(item.id)
    return {"id": item.id, "status": item.status}

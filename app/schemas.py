from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, Field


class ProjectCreate(BaseModel):
    """Request to create a project."""

    name: str = Field(min_length=1, max_length=200)


class TargetCreate(BaseModel):
    """Request to register a target."""

    project_id: str
    name: str = Field(min_length=1, max_length=200)
    image: str | None = None
    url: AnyHttpUrl = "http://demo-target:8080"


class ScopeCreate(BaseModel):
    """Request to create an authorization scope."""

    project_id: str
    target_id: str
    allowed_url: AnyHttpUrl
    expires_at: datetime


class AssessmentCreate(BaseModel):
    """Request to start an assessment."""

    project_id: str
    target_id: str
    scope_id: str
    profile: str = "passive"


class AssessmentOut(BaseModel):
    """Minimal persisted assessment response."""

    id: str
    status: str
    result: dict | None = None


"""Pydantic request and response schemas for the API."""

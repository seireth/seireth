from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, Field

from .models import AssessmentStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TargetCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=200)
    image: str | None = None
    url: AnyHttpUrl = "http://demo-target:8080"


class ScopeCreate(BaseModel):
    project_id: str
    target_id: str
    allowed_url: AnyHttpUrl
    expires_at: datetime


class AssessmentCreate(BaseModel):
    project_id: str
    target_id: str
    scope_id: str
    profile: str = "passive"


class AssessmentOut(BaseModel):
    id: str
    status: AssessmentStatus
    cleanup_pending: bool = False
    result: dict | None = None

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .constraints import NAME_MAX_LENGTH, StoredHttpUrl, TargetImage
from .models import AssessmentStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)


class TargetCreate(BaseModel):
    project_id: str
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    image: TargetImage | None = None
    url: StoredHttpUrl = Field(default="http://demo-target:8080", validate_default=True)


class ScopeCreate(BaseModel):
    project_id: str
    target_id: str
    allowed_url: StoredHttpUrl
    expires_at: datetime


class AssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    target_id: str
    scope_id: str
    plugins: list[str] = Field(min_length=1)


class AssessmentOut(BaseModel):
    id: str
    status: AssessmentStatus
    plugins: list[str]
    cleanup_pending: bool = False
    result: dict | None = None

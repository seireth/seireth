from datetime import datetime
from typing import Literal

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


class HeaderEvidenceData(BaseModel):
    """Public response evidence; arbitrary stored JSON is never exposed."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    url: StoredHttpUrl
    header: Literal[
        "x-content-type-options", "content-security-policy", "x-frame-options"
    ]


class CookieEvidenceData(HeaderEvidenceData):
    header: Literal["set-cookie"]
    cookie_name: str = Field(min_length=1)
    secure: bool


class SameSiteEvidenceData(CookieEvidenceData):
    rule: Literal["samesite-none-without-secure"]
    samesite: Literal["none"]


class SecurePrefixEvidenceData(CookieEvidenceData):
    rule: Literal["secure-prefix"]
    https: bool


class HostPrefixEvidenceData(CookieEvidenceData):
    rule: Literal["host-prefix"]
    https: bool
    domain_present: bool
    root_path: bool


class EvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    id: str
    finding_id: str
    kind: Literal["http-response"]
    data: (
        HeaderEvidenceData
        | SameSiteEvidenceData
        | SecurePrefixEvidenceData
        | HostPrefixEvidenceData
    )


class AssessmentEvidenceOut(BaseModel):
    assessment_id: str
    status: AssessmentStatus
    cleanup_pending: bool
    evidence: list[EvidenceOut]

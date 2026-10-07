from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..assessments.policy import bounded_url
from ..core.constraints import (
    NAME_MAX_LENGTH,
    NormalizedMediaType,
    StoredHttpUrl,
    TargetImage,
)
from ..persistence.models import AssessmentStatus
from ..plugins.http_security_headers_contract import (
    EVIDENCE_CONDITIONS,
    RULE_REQUIREMENTS,
    HeaderCondition,
    HeaderName,
    HeaderRequirement,
    HeaderRuleId,
)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)


class ResponseUrlInput(BaseModel):
    url: StoredHttpUrl

    @field_validator("url", mode="before")
    @classmethod
    def safe_url(cls, value):
        # Check before normalization can erase traversal or backslashes.
        if isinstance(value, str) and not bounded_url(value, value):
            raise ValueError("URL contains unsafe or ambiguous components")
        return value


class TargetCreate(ResponseUrlInput):
    project_id: str
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    image: TargetImage


class AssessmentCreate(ResponseUrlInput):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    target_id: str
    plugins: list[str] = Field(min_length=1)


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AssessmentOut(ReadModel):
    id: str
    project_id: str
    target_id: str
    url: str
    created_at: datetime
    status: AssessmentStatus
    plugins: list[str]
    cleanup_pending: bool = False
    result: dict | None = None


class ProjectOut(ReadModel):
    id: str
    name: str
    created_at: datetime


class TargetOut(ReadModel):
    id: str
    project_id: str
    name: str
    image: str
    url: str


class PageOut[Item](BaseModel):
    items: list[Item]
    has_more: bool


class FindingOut(ReadModel):
    id: str
    plugin: str
    title: str
    severity: str
    description: str
    remediation: str


class AssessmentResultsOut(BaseModel):
    assessment_id: str
    status: AssessmentStatus
    cleanup_pending: bool
    result: dict | None
    findings: list[FindingOut]


class RuntimeOut(BaseModel):
    sandbox_backend: Literal["inmemory", "docker"]


class TargetImageOut(BaseModel):
    image: str
    id: str


class TargetImagesOut(BaseModel):
    items: list[TargetImageOut]


class ResponseEvidenceData(BaseModel):
    """Public response evidence; arbitrary stored JSON is never exposed."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    url: StoredHttpUrl


class HeaderEvidenceData(ResponseEvidenceData):
    header: HeaderName
    rule_id: HeaderRuleId
    status_code: int = Field(ge=100, le=599)
    media_type: NormalizedMediaType | None
    condition: HeaderCondition
    expected: HeaderRequirement

    @model_validator(mode="after")
    def consistent_rule_evidence(self):
        conditions = EVIDENCE_CONDITIONS.get((self.rule_id, self.header), ())
        if (
            self.expected != RULE_REQUIREMENTS[self.rule_id]
            or self.condition not in conditions
        ):
            raise ValueError("header evidence contradicts its rule")
        return self


class CookieEvidenceData(ResponseEvidenceData):
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

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..assessments.plans import FrozenPlan, RoutePlan, read_snapshot
from ..assessments.policy import ResponseUrl
from ..assessments.results import AssessmentResult
from ..core.constraints import (
    NAME_MAX_LENGTH,
    TargetImage,
)
from ..persistence.models import AssessmentStatus
from ..plugins.evidence import EvidenceData


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)


class TargetCreate(BaseModel):
    url: ResponseUrl
    project_id: str
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    kind: Literal["docker", "website"] = "docker"
    image: TargetImage | None = Field(default=None, validate_default=True)
    launch_profile: str | None = Field(default=None, max_length=100)
    network_profile: str | None = Field(default=None, max_length=100)
    trust_profile: str | None = Field(default=None, max_length=100)

    @field_validator("image")
    @classmethod
    def docker_image(cls, value, info):
        if info.data.get("kind", "docker") == "docker" and value is None:
            raise ValueError("Docker target requires an image")
        return value

    @model_validator(mode="after")
    def target_source(self):
        if self.kind == "website" and (self.image or self.launch_profile):
            raise ValueError("website target cannot select an image or launch profile")
        return self


class AssessmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    target_id: str
    url: ResponseUrl | None = None
    routes: list[RoutePlan] | None = Field(default=None, min_length=1, max_length=20)
    plugins: list[str] | None = Field(default=None, min_length=1, validate_default=True)
    baseline: str | None = None

    @field_validator("plugins")
    @classmethod
    def selection_required(cls, value, info):
        if info.data.get("routes") is None and value is None:
            raise ValueError("plugins are required for single URL requests")
        return value

    @model_validator(mode="after")
    def one_form(self):
        if self.routes is not None:
            if self.url is not None or self.plugins is not None:
                raise ValueError("select either routes or URL and plugins")
        elif self.url is None or self.plugins is None:
            raise ValueError("URL and plugins are required")
        return self


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
    result: AssessmentResult | None = None
    plan_snapshot: FrozenPlan

    @field_validator("plan_snapshot", mode="before")
    @classmethod
    def validated_snapshot(cls, value):
        if isinstance(value, FrozenPlan):
            value = value.model_dump(mode="json")
        return read_snapshot(value)


class ProjectOut(ReadModel):
    id: str
    name: str
    created_at: datetime


class TargetOut(ReadModel):
    id: str
    project_id: str
    name: str
    image: str | None
    url: str
    kind: Literal["docker", "website"]
    launch_profile: str | None = None
    network_profile: str | None = None
    trust_profile: str | None = None


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
    route_result_id: str


class AssessmentResultsOut(BaseModel):
    assessment_id: str
    status: AssessmentStatus
    cleanup_pending: bool
    result: AssessmentResult | None
    findings: list[FindingOut]


class TargetImageOut(BaseModel):
    image: str
    id: str


class TargetImagesOut(BaseModel):
    items: list[TargetImageOut]


class EvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    id: str
    finding_id: str
    kind: Literal["http-response"]
    data: EvidenceData


class AssessmentEvidenceOut(BaseModel):
    assessment_id: str
    status: AssessmentStatus
    cleanup_pending: bool
    evidence: list[EvidenceOut]


class ReportAssessmentOut(AssessmentOut):
    result: AssessmentResult


class AssessmentReportOut(BaseModel):
    schema_version: Literal[1]
    generated_at: datetime
    project: ProjectOut
    target: TargetOut
    assessment: ReportAssessmentOut
    findings: list[FindingOut]
    evidence: list[EvidenceOut]

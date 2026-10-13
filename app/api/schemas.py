from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..assessments.plans import FrozenPlan, RoutePlan
from ..assessments.policy import ResponseUrl
from ..core.constraints import (
    NAME_MAX_LENGTH,
    NormalizedMediaType,
    PluginVersion,
    StoredHttpUrl,
    TargetImage,
)
from ..persistence.models import AssessmentStatus
from ..plugins.base import CheckOutcome, require_unique_check_ids
from ..plugins.csp_policy_contract import (
    CONTEXT_CONDITIONS,
    CONTEXT_DIRECTIVES,
    MAX_CSP_POLICIES,
    RULE_CONTEXTS,
    CspCondition,
    CspContext,
    CspDirective,
    CspRuleId,
)
from ..plugins.http_security_headers_contract import (
    EVIDENCE_CONDITIONS,
    RULE_REQUIREMENTS,
    HeaderCondition,
    HeaderName,
    HeaderRequirement,
    HeaderRuleId,
)
from ..plugins.response_context import unevaluated_check

_TIMESTAMP_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?"
    r"(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)


class ResponseUrlInput(BaseModel):
    url: ResponseUrl


class TargetCreate(ResponseUrlInput):
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
    result: dict | None = None
    plan_snapshot: FrozenPlan


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
    result: dict | None
    findings: list[FindingOut]


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


class CspPolicyObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    policy_index: int = Field(ge=1, le=MAX_CSP_POLICIES)
    context: CspContext
    directive: CspDirective | None
    condition: CspCondition

    @model_validator(mode="after")
    def consistent_observation(self):
        if (
            self.condition not in CONTEXT_CONDITIONS[self.context]
            or (self.condition == "missing-directive") != (self.directive is None)
            or (
                self.directive is not None
                and self.directive not in CONTEXT_DIRECTIVES[self.context]
            )
        ):
            raise ValueError("CSP observation contradicts its execution context")
        return self


class CspEvidenceData(ResponseEvidenceData):
    header: Literal["content-security-policy"]
    rule_id: CspRuleId
    status_code: int = Field(ge=100, le=599)
    media_type: NormalizedMediaType
    policy_count: int = Field(ge=1, le=MAX_CSP_POLICIES)
    observations: list[CspPolicyObservation] = Field(
        min_length=1, max_length=2 * MAX_CSP_POLICIES
    )

    @model_validator(mode="after")
    def consistent_policy_coverage(self):
        covered = {}
        for item in self.observations:
            if item.context not in RULE_CONTEXTS[self.rule_id]:
                raise ValueError("CSP evidence contradicts its rule")
            indexes = covered.setdefault(item.context, set())
            if item.policy_index in indexes:
                raise ValueError(
                    "CSP observations must be unique per policy and context"
                )
            indexes.add(item.policy_index)
        expected = set(range(1, self.policy_count + 1))
        if unevaluated_check(
            self.rule_id, self.status_code, self.media_type
        ) is not None or any(indexes != expected for indexes in covered.values()):
            raise ValueError(
                "CSP evidence requires document context and complete policy coverage"
            )
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


class SessionCookieEvidenceData(CookieEvidenceData):
    rule: Literal["session-cookie-secure", "session-cookie-httponly"]
    httponly: bool


class EvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    id: str
    finding_id: str
    kind: Literal["http-response"]
    data: (
        HeaderEvidenceData
        | CspEvidenceData
        | SameSiteEvidenceData
        | SecurePrefixEvidenceData
        | HostPrefixEvidenceData
        | SessionCookieEvidenceData
    )


class AssessmentEvidenceOut(BaseModel):
    assessment_id: str
    status: AssessmentStatus
    cleanup_pending: bool
    evidence: list[EvidenceOut]


class ReportData(BaseModel):
    """Project only documented result fields, without coercing stored values."""

    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class ReportResponseOut(ReportData):
    status_code: int = Field(ge=100, le=599)
    media_type: NormalizedMediaType | None


class ReportPluginOut(ReportData):
    id: str
    finding_count: int = Field(ge=0)
    checks: list[CheckOutcome]

    @field_validator("checks")
    @classmethod
    def unique_checks(cls, checks):
        require_unique_check_ids(checks)
        return checks


class ReportExecutionPluginOut(ReportData):
    id: str
    version: PluginVersion


class ReportExecutionOut(ReportData):
    started_at: str = Field(pattern=_TIMESTAMP_PATTERN)
    deadline_at: str = Field(pattern=_TIMESTAMP_PATTERN)
    target: TargetOut
    plugins: list[ReportExecutionPluginOut]

    @field_validator("started_at", "deadline_at")
    @classmethod
    def valid_execution_time(cls, value):
        # The field pattern requires a timezone; parsing checks the calendar date.
        datetime.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def consistent_execution(self):
        if datetime.fromisoformat(self.deadline_at) <= datetime.fromisoformat(
            self.started_at
        ):
            raise ValueError("execution deadline must follow its start")
        if not self.plugins or len({plugin.id for plugin in self.plugins}) != len(
            self.plugins
        ):
            raise ValueError("execution requires a unique nonempty plugin selection")
        return self


class RouteCoverageOut(ReportData):
    complete: bool
    expected_response: bool
    missing_checks: list[str]
    failed_checks: list[str]


class RouteResponseOut(ReportResponseOut):
    url: StoredHttpUrl
    redirects: list[dict[str, str | int]]


class ReportRouteOut(ReportData):
    id: str | None = None
    key: str
    url: StoredHttpUrl
    status: Literal["completed", "failed", "unattempted"]
    started_at: str | None = Field(default=None, pattern=_TIMESTAMP_PATTERN)
    finished_at: str | None = Field(default=None, pattern=_TIMESTAMP_PATTERN)
    error: str | None = None
    error_kind: Literal["timeout", "plugin_error", "execution_error"] | None = None
    failed_plugin: str | None = None
    response: RouteResponseOut | None = None
    plugins: list[ReportPluginOut]
    finding_count: int = Field(ge=0)
    coverage: RouteCoverageOut


class VerdictOut(ReportData):
    policy: Literal["strict-v1"]
    status: Literal["pass", "blocked"]
    reasons: list[str]


class ComparisonOut(ReportData):
    status: Literal["not_requested", "unavailable", "available"]
    reason: str | None = None
    algorithm: Literal[1] | None = None
    baseline: str | None = None
    new: list[list[str]] | None = None
    resolved: list[list[str]] | None = None
    unchanged: list[list[str]] | None = None


class ReportResultOut(ReportData):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    sandbox_backend: Literal["docker", "http"] | None = None
    attempt: int | None = Field(default=None, ge=1)
    completed_at: str | None = Field(
        default=None,
        pattern=_TIMESTAMP_PATTERN,
    )
    error: str | None = None
    error_kind: Literal["timeout", "plugin_error", "execution_error"] | None = None
    failed_plugin: str | None = None
    execution: ReportExecutionOut | None = None
    cleanup_verified: bool
    cleanup_reason: str | None = None
    finding_count: int = Field(ge=0)

    @model_validator(mode="before")
    @classmethod
    def supplied_fields_are_not_null(cls, value):
        if isinstance(value, dict) and any(
            value[key] is None
            for key in cls.model_fields
            if key in value and key != "cleanup_reason"
        ):
            raise ValueError("supplied execution fields must not be null")
        return value

    @field_validator("completed_at")
    @classmethod
    def valid_completion_time(cls, value):
        if value is not None:
            # The pattern ensures a browser-readable format; parsing checks the date.
            datetime.fromisoformat(value)
        return value

    execution_outcome: Literal[
        "completed", "failed", "cancelled", "interrupted", "not_started"
    ]
    routes: list[ReportRouteOut]
    coverage: dict[str, bool]
    verdict: VerdictOut
    comparison: ComparisonOut
    partial: bool


class ReportAssessmentOut(AssessmentOut):
    result: ReportResultOut
    plan_snapshot: FrozenPlan


class AssessmentReportOut(BaseModel):
    schema_version: Literal[1]
    generated_at: datetime
    project: ProjectOut
    target: TargetOut
    assessment: ReportAssessmentOut
    findings: list[FindingOut]
    evidence: list[EvidenceOut]

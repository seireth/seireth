"""Validated, redacted evidence shared by plugins, persistence, and APIs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ..core.constraints import NormalizedMediaType, StoredHttpUrl
from .csp_policy_contract import (
    CONTEXT_CONDITIONS,
    CONTEXT_DIRECTIVES,
    MAX_CSP_POLICIES,
    RULE_CONTEXTS,
    CspCondition,
    CspContext,
    CspDirective,
    CspRuleId,
)
from .http_security_headers_contract import (
    EVIDENCE_CONDITIONS,
    RULE_REQUIREMENTS,
    HeaderCondition,
    HeaderName,
    HeaderRequirement,
    HeaderRuleId,
)
from .response_context import unevaluated_check


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
    rule_id: Literal["samesite-none-without-secure"]
    samesite: Literal["none"]


class SecurePrefixEvidenceData(CookieEvidenceData):
    rule_id: Literal["secure-prefix"]
    https: bool


class HostPrefixEvidenceData(CookieEvidenceData):
    rule_id: Literal["host-prefix"]
    https: bool
    domain_present: bool
    root_path: bool


class SessionCookieEvidenceData(CookieEvidenceData):
    rule_id: Literal["session-cookie-secure", "session-cookie-httponly"]
    httponly: bool


EvidenceData = (
    HeaderEvidenceData
    | CspEvidenceData
    | SameSiteEvidenceData
    | SecurePrefixEvidenceData
    | HostPrefixEvidenceData
    | SessionCookieEvidenceData
)
evidence_adapter = TypeAdapter(EvidenceData)

"""One public assessment-result contract, independent of API transport."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..core.constraints import NormalizedMediaType, PluginVersion, StoredHttpUrl
from ..plugins.base import CheckOutcome, require_unique_check_ids
from .plans import FrozenTarget

_TIMESTAMP_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?"
    r"(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)


class ResultData(BaseModel):
    """Project only documented result fields, without coercing stored values."""

    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class PluginOutcome(ResultData):
    id: str
    finding_count: int = Field(ge=0)
    checks: list[CheckOutcome]

    @field_validator("checks")
    @classmethod
    def unique_checks(cls, checks):
        require_unique_check_ids(checks)
        return checks


class ExecutionPlugin(ResultData):
    id: str
    version: PluginVersion


class ExecutionMetadata(ResultData):
    started_at: str = Field(pattern=_TIMESTAMP_PATTERN)
    deadline_at: str = Field(pattern=_TIMESTAMP_PATTERN)
    target: FrozenTarget
    plugins: list[ExecutionPlugin]

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


class RouteCoverage(ResultData):
    complete: bool
    expected_response: bool
    missing_checks: list[str]
    failed_checks: list[str]


class RouteResponse(ResultData):
    status_code: int = Field(ge=100, le=599)
    media_type: NormalizedMediaType | None
    url: StoredHttpUrl
    redirects: list[dict[str, str | int]]


class RouteOutcome(ResultData):
    id: str | None = None
    key: str
    url: StoredHttpUrl
    status: Literal["completed", "failed", "unattempted"]
    started_at: str | None = Field(default=None, pattern=_TIMESTAMP_PATTERN)
    finished_at: str | None = Field(default=None, pattern=_TIMESTAMP_PATTERN)
    error: str | None = None
    error_kind: Literal["timeout", "plugin_error", "execution_error"] | None = None
    failed_plugin: str | None = None
    response: RouteResponse | None = None
    plugins: list[PluginOutcome]
    finding_count: int = Field(ge=0)
    coverage: RouteCoverage


class ReleaseVerdict(ResultData):
    policy: Literal["strict-v1"]
    status: Literal["pass", "blocked"]
    reasons: list[str]


class BaselineComparison(ResultData):
    status: Literal["not_requested", "unavailable", "available"]
    reason: str | None = None
    algorithm: Literal[1] | None = None
    baseline: str | None = None
    new: list[list[str]] | None = None
    resolved: list[list[str]] | None = None
    unchanged: list[list[str]] | None = None


class AssessmentResult(ResultData):
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
    execution: ExecutionMetadata | None = None
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
    routes: list[RouteOutcome]
    coverage: dict[str, bool]
    verdict: ReleaseVerdict
    comparison: BaselineComparison
    partial: bool

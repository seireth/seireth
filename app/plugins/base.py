"""Typed, JSON-compatible contract for response-analysis plugins."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from ..core.constraints import (
    FINDING_SEVERITY_MAX_LENGTH,
    FINDING_TITLE_MAX_LENGTH,
    MEDIA_TYPE_PATTERN,
    PLUGIN_ID_MAX_LENGTH,
    StoredHttpUrl,
)

_PLUGIN_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_TOKEN = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_MEDIA_TYPE = re.compile(
    rf"[ \t]*(?P<media>(?ai:{MEDIA_TYPE_PATTERN}))[ \t]*"
    rf'(?:;[ \t]*{_TOKEN}[ \t]*=[ \t]*(?:{_TOKEN}|"(?:[^"\\\x00-\x1f\x7f]|\\[\x20-\x7e])*")[ \t]*)*'
)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class HttpObservation(ContractModel):
    url: StoredHttpUrl
    status_code: int = Field(ge=100, le=599)
    headers: dict[str, list[str]]

    @property
    def media_type(self) -> str | None:
        fields = self.headers.get("content-type", [])
        if not fields:
            return None
        types = set()
        for value in fields:
            # Do not guess a type from malformed or conflicting fields.
            match = _MEDIA_TYPE.fullmatch(value)
            if match is None:
                return None
            types.add(match["media"].lower())
        return types.pop() if len(types) == 1 else None

    @field_validator("headers")
    @classmethod
    def normalize_headers(cls, headers: dict[str, list[str]]) -> dict[str, list[str]]:
        normalized: dict[str, list[str]] = {}
        for name, values in headers.items():
            if not values:
                raise ValueError("header fields require at least one value")
            normalized.setdefault(name.lower(), []).extend(values)
        return normalized


class PluginManifest(ContractModel):
    id: str = Field(
        min_length=1, max_length=PLUGIN_ID_MAX_LENGTH, pattern=_PLUGIN_ID_PATTERN
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)


class PluginFinding(ContractModel):
    title: str = Field(min_length=1, max_length=FINDING_TITLE_MAX_LENGTH)
    severity: str = Field(min_length=1, max_length=FINDING_SEVERITY_MAX_LENGTH)
    description: str = Field(min_length=1)
    remediation: str = Field(min_length=1)
    evidence: dict[str, JsonValue]

    @field_validator("description", "remediation")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("finding text must not be blank")
        return value


class CheckOutcome(ContractModel):
    rule_id: str = Field(min_length=1, max_length=100, pattern=_PLUGIN_ID_PATTERN)
    status: Literal["passed", "failed", "skipped", "inconclusive"]
    reason: str = Field(min_length=1, max_length=300)

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("check reason must not be blank")
        return value


def require_unique_check_ids(checks: Sequence[CheckOutcome]) -> None:
    if len({check.rule_id for check in checks}) != len(checks):
        raise ValueError("check rule IDs must be unique")


class PluginResponse(ContractModel):
    findings: tuple[PluginFinding, ...]
    checks: tuple[CheckOutcome, ...] = ()

    @model_validator(mode="after")
    def unique_checks(self):
        require_unique_check_ids(self.checks)
        return self


@dataclass(frozen=True)
class Plugin:
    manifest: PluginManifest
    analyze: Callable[[HttpObservation], PluginResponse]


@dataclass(frozen=True)
class PluginResult:
    plugin_id: str
    findings: tuple[PluginFinding, ...]
    checks: tuple[CheckOutcome, ...] = ()

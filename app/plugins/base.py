"""Typed, JSON-compatible contract for response-analysis plugins."""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
)

from ..core.constraints import (
    FINDING_SEVERITY_MAX_LENGTH,
    FINDING_TITLE_MAX_LENGTH,
    PLUGIN_ID_MAX_LENGTH,
    StoredHttpUrl,
)

_PLUGIN_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


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
    headers: dict[str, list[str]]

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


class PluginResponse(ContractModel):
    findings: tuple[PluginFinding, ...]


@dataclass(frozen=True)
class Plugin:
    manifest: PluginManifest
    analyze: Callable[[HttpObservation], PluginResponse]


@dataclass(frozen=True)
class PluginResult:
    plugin_id: str
    findings: tuple[PluginFinding, ...]

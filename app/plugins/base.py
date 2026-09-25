"""Versioned, JSON-compatible contract for response-analysis plugins."""

from collections.abc import Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
)

from ..constraints import (
    FINDING_SEVERITY_MAX_LENGTH,
    FINDING_TITLE_MAX_LENGTH,
    PLUGIN_ID_MAX_LENGTH,
    StoredHttpUrl,
)

PLUGIN_CONTRACT_VERSION = 1
_PLUGIN_ID_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


class HttpObservation(ContractModel):
    contract_version: Literal[1] = PLUGIN_CONTRACT_VERSION
    url: StoredHttpUrl
    headers: dict[str, str]


class PluginManifest(ContractModel):
    contract_version: Literal[1] = PLUGIN_CONTRACT_VERSION
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
    contract_version: Literal[1] = PLUGIN_CONTRACT_VERSION
    findings: tuple[PluginFinding, ...]


@dataclass(frozen=True)
class Plugin:
    manifest: PluginManifest
    analyze: Callable[[HttpObservation], PluginResponse]


@dataclass(frozen=True)
class PluginResult:
    plugin_id: str
    findings: tuple[PluginFinding, ...]


@dataclass(frozen=True)
class PluginRegistry:
    plugins: tuple[Plugin, ...]
    _by_id: MappingProxyType = field(init=False, repr=False)

    def __post_init__(self) -> None:
        validated_plugins = []
        for plugin in self.plugins:
            if not isinstance(plugin, Plugin) or not callable(plugin.analyze):
                raise ValueError("registered plugins must satisfy the plugin contract")
            try:
                manifest = PluginManifest.model_validate(plugin.manifest, strict=True)
            except (TypeError, ValidationError) as exc:
                raise ValueError("registered plugin has an invalid manifest") from exc
            validated_plugins.append(Plugin(manifest=manifest, analyze=plugin.analyze))
        plugins = tuple(validated_plugins)
        ids = [plugin.manifest.id for plugin in plugins]
        if len(ids) != len(set(ids)):
            raise ValueError("plugin IDs must be unique")
        by_id = {plugin.manifest.id: plugin for plugin in plugins}
        object.__setattr__(self, "plugins", plugins)
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))

    def select(self, ids: list[str]) -> list[Plugin]:
        """Resolve an ordered, nonempty selection against the approved registry."""

        if not isinstance(ids, list) or any(
            not isinstance(value, str) for value in ids
        ):
            raise ValueError("invalid plugin selection")
        if not ids:
            raise ValueError("at least one plugin is required")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate plugins are not allowed")
        if any(plugin_id not in self._by_id for plugin_id in ids):
            raise ValueError("unknown or inactive plugin")
        return [self._by_id[plugin_id] for plugin_id in ids]

    def catalog(self) -> list[dict]:
        return [
            plugin.manifest.model_dump(include={"id", "name", "description"})
            for plugin in self.plugins
        ]

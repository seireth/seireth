"""Small interface shared by built-in response analysis plugins."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class PluginFinding:
    title: str
    severity: str
    description: str
    remediation: str
    evidence: dict


@dataclass(frozen=True)
class PluginResult:
    plugin_id: str
    findings: list[PluginFinding]


@dataclass(frozen=True)
class Plugin:
    id: str
    name: str
    description: str
    profiles: tuple[str, ...]
    run: Callable[[Mapping[str, str], str], list[PluginFinding]]

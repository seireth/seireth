"""Approved built-in plugins and validated selection for API and worker use."""

from dataclasses import dataclass, field
from types import MappingProxyType

from pydantic import ValidationError

from .base import Plugin, PluginManifest
from .cookie_security import PLUGIN as COOKIE_SECURITY_PLUGIN
from .security_headers import PLUGIN as SECURITY_HEADERS_PLUGIN


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


registry = PluginRegistry(plugins=(SECURITY_HEADERS_PLUGIN, COOKIE_SECURITY_PLUGIN))

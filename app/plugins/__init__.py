"""Built-in passive assessment plugins and their stable public identities."""

from .base import Plugin
from .base import PluginResult as PluginResult
from .security_headers import security_headers

PLUGINS = (
    Plugin(
        id="security-headers",
        name="HTTP security headers",
        description="Check three browser security headers on the target response.",
        profiles=("passive",),
        run=security_headers,
    ),
)
BY_ID = {plugin.id: plugin for plugin in PLUGINS}
DEFAULT_PLUGINS = ("security-headers",)


def select_plugins(ids: list[str] | None, profile: str) -> list[Plugin]:
    """Resolve an ordered, nonempty selection against the built-in registry."""

    if ids is not None and (
        not isinstance(ids, list) or any(not isinstance(value, str) for value in ids)
    ):
        raise ValueError("invalid plugin selection")
    selected = list(DEFAULT_PLUGINS if ids is None else ids)
    if not selected:
        raise ValueError("at least one plugin is required")
    if len(selected) != len(set(selected)):
        raise ValueError("duplicate plugins are not allowed")
    if any(plugin_id not in BY_ID for plugin_id in selected):
        raise ValueError("unknown plugin")
    plugins = [BY_ID[plugin_id] for plugin_id in selected]
    if any(profile not in plugin.profiles for plugin in plugins):
        raise ValueError("plugin is not supported by this profile")
    return plugins


def catalog() -> list[dict]:
    return [
        {
            "id": plugin.id,
            "name": plugin.name,
            "description": plugin.description,
            "profiles": list(plugin.profiles),
        }
        for plugin in PLUGINS
    ]

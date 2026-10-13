"""Execute a single attempt without holding a database transaction."""

from dataclasses import dataclass

from pydantic import ValidationError

from ..plugins.base import PluginResponse, PluginResult


def sandbox_for(attempt, *, snapshot, persist_journal, context=None):
    if attempt.backend == "docker":
        from .bundle import BundleSession

        return BundleSession(
            snapshot, attempt, persist_journal=persist_journal, context=context
        )
    if attempt.backend == "http":
        from .website import WebsiteSession

        return WebsiteSession(
            snapshot,
            context,
            attempt.execution_metadata["process_identity"].get("addresses", ()),
        )
    raise ValueError("unsupported execution backend")


@dataclass
class Outcome:
    status: str = "completed"
    error: str | None = None
    cleanup_verified: bool = False
    cleanup_reason: str | None = None
    error_kind: str | None = None
    failed_plugin: str | None = None
    execution_status: str | None = None


class PluginExecutionError(RuntimeError):
    """A safe plugin failure description, separate from security findings."""

    def __init__(self, plugin_id, *, invalid=False):
        self.plugin_id = plugin_id
        super().__init__(
            f"plugin {plugin_id} returned an invalid response"
            if invalid
            else f"plugin {plugin_id} execution failed"
        )


def analyze_response(observation, plugins, context, analysis):
    results = []
    for plugin in plugins:
        try:
            value = plugin.analyze(observation.model_copy(deep=True), analysis)
            response = PluginResponse.model_validate(value, strict=True)
        except ValidationError as exc:
            raise PluginExecutionError(plugin.manifest.id, invalid=True) from exc
        except Exception as exc:
            raise PluginExecutionError(plugin.manifest.id) from exc
        results.append(
            PluginResult(plugin.manifest.id, response.findings, response.checks)
        )
        context.check()
    return results

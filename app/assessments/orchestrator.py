"""Execute a single attempt without holding a database transaction."""

import logging
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from pydantic import ValidationError

from ..core.config import settings
from ..plugins.base import Plugin, PluginResponse, PluginResult
from .execution import Cancelled, Interrupted
from .sandbox import DockerSandbox, InMemorySandbox

logger = logging.getLogger(__name__)


def sandbox_for(attempt, target=None, context=None, persist_journal=None):
    if attempt.backend == "inmemory":
        return InMemorySandbox(context=context)
    if attempt.backend != "docker":
        raise ValueError("unsupported sandbox backend")
    return DockerSandbox(
        target.image if target else None,
        runner_image=settings.docker_runner_image,
        assessment_id=attempt.assessment_id,
        attempt_id=attempt.id,
        resources=attempt.resources or None,
        target_host=urlsplit(target.url).hostname if target else None,
        memory=settings.docker_memory,
        cpus=settings.docker_cpus,
        pids_limit=settings.docker_pids_limit,
        command_timeout=settings.docker_timeout_seconds,
        context=context,
        operation_journal=attempt.operation_journal,
        persist_journal=persist_journal,
    )


@dataclass
class Outcome:
    status: str = "completed"
    error: str | None = None
    cleanup_verified: bool = False
    plugin_results: list[PluginResult] = field(default_factory=list)
    cleanup_reason: str | None = None


def execute(sandbox, url, context, plugins: list[Plugin]) -> Outcome:
    outcome = Outcome()
    try:
        context.check()
        observation = sandbox.execute(url)
        context.check()
        for plugin in plugins:
            try:
                response = PluginResponse.model_validate(
                    plugin.analyze(observation.model_copy(deep=True)), strict=True
                )
            except ValidationError as exc:
                raise ValueError(
                    f"plugin {plugin.manifest.id} returned an invalid response"
                ) from exc
            outcome.plugin_results.append(
                PluginResult(plugin.manifest.id, response.findings)
            )
            context.check()
    except Cancelled:
        outcome.status, outcome.error = "cancelled", "assessment cancelled"
    except Interrupted:
        outcome.status, outcome.error = "recovering", "execution interrupted"
    except TimeoutError:
        outcome.status, outcome.error = "failed", "assessment execution timed out"
    except Exception:
        logger.exception("assessment execution failed")
        outcome.status, outcome.error = "failed", "assessment execution failed"
    finally:
        try:
            cleanup = sandbox.cleanup()
            outcome.cleanup_verified = cleanup.verified
            outcome.cleanup_reason = cleanup.reason
        except Exception:
            logger.exception("assessment cleanup failed")
            outcome.cleanup_reason = "cleanup could not be completed"
        if not outcome.cleanup_verified:
            outcome.status = "failed"
            outcome.error = outcome.error or "sandbox cleanup could not be verified"
    return outcome

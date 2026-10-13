"""Durable resource identity validation and bounded Docker commands."""

import os
import re
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from time import monotonic
from uuid import UUID

_RESOURCE_ID = re.compile(r"[a-f0-9]{64}")


@dataclass(frozen=True)
class CleanupOutcome:
    verified: bool
    reason: str | None = None


def validate_journal(journal):
    """Reject corrupt ownership data rather than inventing cleanup history."""
    try:
        UUID(journal["owner"])
        if journal["version"] != 1 or set(journal) != {"version", "owner", "resources"}:
            raise ValueError("invalid journal fields")
        for entry in journal["resources"].values():
            if entry["kind"] not in {"container", "network", "volume"} or entry[
                "state"
            ] not in {"not_requested", "uncertain", "created", "removed"}:
                raise ValueError("invalid resource journal")
            if not re.fullmatch(r"seireth-[a-z0-9-]+", entry["name"]):
                raise ValueError("invalid resource name")
            if entry["state"] in {"not_requested", "uncertain"}:
                if entry["id"] is not None:
                    raise ValueError("invalid uncertain resource identity")
            elif entry["kind"] == "volume":
                if (
                    entry["id"] != entry["name"]
                    or not isinstance(entry.get("created_at"), str)
                    or not entry["created_at"].strip()
                ):
                    raise ValueError("invalid volume identity")
            elif not _RESOURCE_ID.fullmatch(entry["id"] or ""):
                raise ValueError("invalid Docker identity")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("invalid operation journal") from exc


class DockerCommands:
    """Commands share attempt fencing with bundle creation and cleanup."""

    @property
    def labels(self):
        return {
            "seireth.assessment": self.assessment_id,
            "seireth.attempt": self.attempt_id,
        }

    def _guard(self, advancing=False):
        if advancing and self.context:
            self.context.check()
        self.persist_journal(deepcopy(self.journal), advancing=advancing)

    def _run(
        self,
        args: list[str],
        timeout: float,
        *,
        interruptible=True,
        input_data=None,
        extra_env=None,
    ):
        """Bound the real CLI process and reap it before attempting resource cleanup."""
        deadline = monotonic() + timeout
        context = self.context if interruptible else None
        self._guard(advancing=interruptible)
        if context:
            context.check()
        with subprocess.Popen(
            ["docker", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if input_data is not None else None,
            text=True,
            env={**os.environ, **extra_env} if extra_env else None,
        ) as process:
            try:
                while True:
                    if context:
                        context.check()
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Docker command timed out")
                    try:
                        stdout, stderr = process.communicate(
                            input=input_data, timeout=min(0.1, remaining)
                        )
                        return subprocess.CompletedProcess(
                            args, process.returncode, stdout, stderr
                        )
                    except subprocess.TimeoutExpired:
                        input_data = None
                        continue
            except BaseException:
                process.kill()
                process.communicate()
                raise

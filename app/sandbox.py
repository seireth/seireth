"""Owned, cancellable Docker resources and independent removal verification."""

import json
import re
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from time import monotonic
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from .execution import ExecutionContext


@dataclass(frozen=True)
class CleanupOutcome:
    verified: bool
    reason: str | None = None


def new_journal():
    return {
        "version": 1,
        "owner": str(uuid4()),
        "resources": {
            kind: {"state": "not_requested", "id": None}
            for kind in ("network", "target", "runner")
        },
    }


def validate_journal(journal):
    """Reject corrupt ownership data rather than inventing cleanup history."""
    try:
        UUID(journal["owner"])
        valid = journal["version"] == 1 and set(journal["resources"]) == {
            "network",
            "target",
            "runner",
        }
        for entry in journal["resources"].values():
            state, identity = entry["state"], entry["id"]
            valid = valid and (
                (state in {"not_requested", "uncertain"} and identity is None)
                or (
                    state in {"created", "removed"}
                    and isinstance(identity, str)
                    and re.fullmatch(r"[a-f0-9]{64}", identity)
                )
            )
        if not valid:
            raise ValueError("invalid journal fields")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("invalid operation journal") from exc


class Sandbox(Protocol):
    def execute(self, url: str, timeout_seconds: float = 5) -> dict[str, str]: ...
    def cleanup(self) -> CleanupOutcome: ...


class InMemorySandbox:
    """Deterministic backend with no network access."""

    def __init__(self, headers=None, context: ExecutionContext | None = None):
        self.headers = headers or {}
        self.context = context

    def execute(self, url: str, timeout_seconds: float = 5) -> dict[str, str]:
        if self.context:
            self.context.check()
        return dict(self.headers)

    def cleanup(self) -> CleanupOutcome:
        return CleanupOutcome(True)


_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,254}$")
_FETCH = """\
import json, sys, time, urllib.request, urllib.error
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
opener = urllib.request.build_opener(NoRedirect)
url, timeout = sys.argv[1], float(sys.argv[2])
deadline = time.monotonic() + timeout
last_error = None
while time.monotonic() < deadline:
    try:
        try:
            response = opener.open(url, timeout=min(2, max(0.1, deadline - time.monotonic())))
        except urllib.error.HTTPError as error:
            response = error
        print(json.dumps(dict(response.headers.items())))
        break
    except OSError as error:
        last_error = error
        time.sleep(0.2)
else:
    raise last_error
"""


class DockerSandbox:
    def __init__(
        self,
        image: str,
        *,
        runner_image: str,
        memory="256m",
        cpus=0.5,
        pids_limit=64,
        target_host=None,
        assessment_id=None,
        attempt_id=None,
        resources=None,
        command_timeout=15,
        context: ExecutionContext | None = None,
        operation_journal,
        persist_journal=None,
    ):
        if not _IMAGE.fullmatch(image) or not _IMAGE.fullmatch(runner_image):
            raise ValueError("invalid Docker image name")
        self.image, self.runner_image = image, runner_image
        self.memory, self.cpus, self.pids_limit = memory, cpus, pids_limit
        self.command_timeout, self.context = command_timeout, context
        self.target_host = target_host
        validate_journal(operation_journal)
        self.journal = deepcopy(operation_journal)
        self.persist_journal = persist_journal
        self.assessment_id = assessment_id or str(uuid4())
        self.attempt_id = attempt_id or str(uuid4())
        token = self.attempt_id.replace("-", "")
        self.resources = resources or {
            "network": "seireth-assessment-" + token,
            "target": "seireth-target-" + token,
            "runner": "seireth-assessment-runner-" + token,
        }
        if set(self.resources) != {"network", "target", "runner"} or any(
            not re.fullmatch(r"seireth-[a-z0-9-]{1,60}", name)
            for name in self.resources.values()
        ):
            raise ValueError("invalid persisted sandbox resource names")

    @property
    def labels(self):
        return {
            "seireth.assessment": self.assessment_id,
            "seireth.attempt": self.attempt_id,
        }

    def _guard(self, advancing=False):
        if advancing and self.context:
            self.context.check()
        if self.persist_journal:
            self.persist_journal(deepcopy(self.journal), advancing)

    def _record(self, kind, state, identity=None, *, advancing=False):
        journal = deepcopy(self.journal)
        journal["resources"][kind] = {"state": state, "id": identity}
        if self.persist_journal:
            self.persist_journal(journal, advancing)
        self.journal = journal

    def _run(self, args: list[str], timeout: float, *, interruptible=True):
        """Bound the real CLI process and reap it before attempting resource cleanup."""
        deadline = monotonic() + timeout
        context = self.context if interruptible else None
        self._guard(advancing=interruptible)
        if context:
            context.check()
        with subprocess.Popen(
            ["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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
                            timeout=min(0.1, remaining)
                        )
                        return subprocess.CompletedProcess(
                            args, process.returncode, stdout, stderr
                        )
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                process.kill()
                process.communicate()
                raise

    def _restricted_args(self):
        return [
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            f"--pids-limit={self.pids_limit}",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
            "--user=65532:65532",
        ]

    def _target_url(self, url):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("sandbox only supports HTTP(S) URLs")
        if parsed.hostname != self.target_host:
            raise ValueError("URL host is outside the registered target")
        return urlunsplit(
            (
                parsed.scheme,
                f"target:{parsed.port}" if parsed.port else "target",
                parsed.path,
                parsed.query,
                "",
            )
        )

    def execute(self, url: str, timeout_seconds: float = 5) -> dict[str, str]:
        target_url = self._target_url(url)
        labels = [
            arg
            for key, value in self.labels.items()
            for arg in ("--label", f"{key}={value}")
        ]
        commands = [
            ["network", "create", "--internal", *labels, self.resources["network"]],
            [
                "create",
                "--name",
                self.resources["target"],
                "--network",
                self.resources["network"],
                "--network-alias",
                "target",
                *labels,
                *self._restricted_args(),
                self.image,
            ],
            [
                "create",
                "--name",
                self.resources["runner"],
                "--network",
                self.resources["network"],
                *labels,
                *self._restricted_args(),
                self.runner_image,
                "python",
                "-c",
                _FETCH,
                target_url,
                str(timeout_seconds),
            ],
        ]
        for kind, args in zip(("network", "target", "runner"), commands):
            if self.journal["resources"][kind]["state"] != "not_requested":
                raise RuntimeError("resource creation was already requested")
            self._guard(advancing=True)
            self._record(kind, "uncertain", advancing=True)
            result = self._run(args, max(self.command_timeout, timeout_seconds + 5))
            if result.returncode:
                raise RuntimeError("Docker sandbox operation failed")
            identity = result.stdout.strip()
            if not re.fullmatch(r"[a-f0-9]{64}", identity):
                raise RuntimeError("Docker returned an invalid resource ID")
            self._record(kind, "created", identity, advancing=True)
            if kind == "target":
                started = self._run(["start", identity], self.command_timeout)
                if started.returncode:
                    raise RuntimeError("Docker target startup failed")
        result = self._run(
            ["start", "--attach", self.journal["resources"]["runner"]["id"]],
            max(self.command_timeout, timeout_seconds + 5),
        )
        if result.returncode:
            raise RuntimeError("Docker runner failed")
        headers = json.loads(result.stdout)
        if not isinstance(headers, dict):
            raise RuntimeError("runner returned invalid headers")
        return {str(k): str(v) for k, v in headers.items()}

    def _owned_id(self, kind, name):
        """Absence is only an observation, not proof that creation has settled."""
        args = (
            ["network", "ls", "--format", "{{.Name}}"]
            if kind == "network"
            else ["ps", "-a", "--format", "{{.Names}}"]
        )
        listed = self._run(args, self.command_timeout, interruptible=False)
        if listed.returncode:
            raise RuntimeError("Cannot enumerate Docker resources")
        if name not in listed.stdout.splitlines():
            return None
        args = (
            ["network", "inspect", name]
            if kind == "network"
            else ["container", "inspect", name]
        )
        inspected = self._run(args, self.command_timeout, interruptible=False)
        if inspected.returncode:
            raise RuntimeError("Cannot verify Docker resource ownership")
        record = json.loads(inspected.stdout)[0]
        labels = (
            record.get("Labels")
            if kind == "network"
            else record.get("Config", {}).get("Labels")
        )
        if not labels or any(
            labels.get(key) != value for key, value in self.labels.items()
        ):
            raise RuntimeError("Docker resource ownership mismatch")
        identity = record.get("Id")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{64}", identity):
            raise RuntimeError("Cannot verify Docker resource identity")
        return identity

    def cleanup(self) -> CleanupOutcome:
        reasons = []
        for kind in ("runner", "target", "network"):
            name = self.resources[kind]
            try:
                self._guard()
                entry = self.journal["resources"][kind]
                identity = self._owned_id(kind, name)
                if identity:
                    if entry["id"] and identity != entry["id"]:
                        raise RuntimeError("Docker resource identity mismatch")
                    # Persist observation before removal: a crash after rm must
                    # not turn a known creation back into permanent uncertainty.
                    self._record(kind, "created", identity)
                    args = (
                        ["network", "rm", identity]
                        if kind == "network"
                        else ["rm", "-f", identity]
                    )
                    self._run(args, self.command_timeout, interruptible=False)
                    entry = self.journal["resources"][kind]
                if self._owned_id(kind, name):
                    reasons.append(f"{kind}: removal not verified")
                elif entry["state"] == "uncertain":
                    reasons.append(f"{kind}: creation outcome unknown")
                elif entry["state"] != "not_requested":
                    self._record(kind, "removed", entry["id"])
            except (
                OSError,
                RuntimeError,
                TimeoutError,
                ValueError,
                KeyError,
                IndexError,
                TypeError,
            ) as exc:
                reasons.append(f"{kind}: {exc}")
        return CleanupOutcome(not reasons, "; ".join(reasons) or None)

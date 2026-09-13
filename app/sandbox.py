"""Disposable assessment sandboxes.

The Docker implementation deliberately uses the Docker CLI rather than a
client library.  This keeps the API process' dependency surface small, while
still making every privileged operation explicit and easy to audit.
"""

from dataclasses import dataclass
import json
import re
import subprocess
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4


@dataclass(frozen=True)
class SandboxResult:
    """Result of a sandbox request, including cleanup details."""

    headers: dict[str, str]
    cleanup_verified: bool
    error: str | None = None


class Sandbox(Protocol):
    """Contract implemented by assessment sandbox backends."""

    def execute(self, url: str, timeout_seconds: float = 5) -> SandboxResult: ...
    def cleanup(self) -> bool: ...


class InMemorySandbox:
    """Deterministic test backend; it performs no network access."""

    backend_name = "inmemory"

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}
        self.cleaned = False

    def execute(self, url: str, timeout_seconds: float = 5) -> SandboxResult:
        """Return deterministic headers without making a network request."""

        return SandboxResult(dict(self.headers), self.cleaned)

    def cleanup(self) -> bool:
        """Mark the in-memory sandbox as cleaned up."""

        self.cleaned = True
        return True


_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,254}$")
_FETCH = """\
import json, sys, time, urllib.request
url, timeout = sys.argv[1], float(sys.argv[2])
deadline = time.monotonic() + timeout
last_error = None
while time.monotonic() < deadline:
    try:
        response = urllib.request.urlopen(url, timeout=min(2, max(0.1, deadline - time.monotonic())))
        print(json.dumps(dict(response.headers.items())))
        break
    except OSError as error:
        last_error = error
        time.sleep(0.2)
else:
    raise last_error
"""


class DockerSandbox:
    """Run a target and a short-lived Python runner on a private Docker network."""

    backend_name = "docker"

    def __init__(
        self,
        image: str,
        *,
        runner_image: str = "python:3.12-slim",
        memory: str = "256m",
        cpus: float = 0.5,
        pids_limit: int = 64,
        network_prefix: str = "seireth-assessment",
        target_host: str | None = None,
        target_user: str = "65532:65532",
        command_timeout: float = 15,
    ):
        if not _IMAGE.fullmatch(image) or not _IMAGE.fullmatch(runner_image):
            raise ValueError("invalid Docker image name")
        if not _NAME.fullmatch(network_prefix):
            raise ValueError("invalid Docker network prefix")
        self.image, self.runner_image = image, runner_image
        self.memory, self.cpus, self.pids_limit = memory, cpus, pids_limit
        self.target_user = target_user
        self.command_timeout = command_timeout
        suffix = uuid4().hex[:12]
        self.network_name = f"{network_prefix}-{suffix}"
        self.target_name = f"{self.network_name}-target"
        self.target_host = target_host
        self.container_id: str | None = None
        self._network_created = False
        self._last_error: str | None = None

    def _run(self, args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        """Run a Docker argv without invoking a shell."""

        try:
            return subprocess.run(
                ["docker", *args], capture_output=True, text=True,
                timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"docker command failed: {exc}") from exc

    def _restricted_args(self) -> list[str]:
        return [
            "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            f"--memory={self.memory}", f"--cpus={self.cpus}",
            f"--pids-limit={self.pids_limit}",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
        ]

    def restricted_run_args(self) -> list[str]:
        """Expose the common hardening flags for callers and command tests."""

        return self._restricted_args()

    def _target_url(self, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("sandbox only supports HTTP(S) URLs")
        if self.target_host is None:
            self.target_host = parsed.hostname
        if parsed.hostname != self.target_host:
            raise ValueError("URL host is outside the registered target")
        return urlunsplit((parsed.scheme, f"target:{parsed.port}" if parsed.port else "target",
                           parsed.path, parsed.query, parsed.fragment))

    def execute(self, url: str, timeout_seconds: float = 5) -> SandboxResult:
        """Create the private network, fetch headers from the target, and retain cleanup state."""

        try:
            target_url = self._target_url(url)
            created = self._run(["network", "create", "--internal", self.network_name],
                                self.command_timeout)
            if created.returncode:
                raise RuntimeError(created.stderr.strip() or "unable to create sandbox network")
            self._network_created = True
            target = self._run([
                "run", "-d", "--name", self.target_name, "--network", self.network_name,
                "--network-alias", "target", *self._restricted_args(),
                *(["--user", self.target_user] if self.target_user else []), self.image,
            ], self.command_timeout)
            if target.returncode:
                raise RuntimeError(target.stderr.strip() or "unable to start target container")
            self.container_id = target.stdout.strip()
            runner = self._run([
                "run", "--rm", "--network", self.network_name, *self._restricted_args(),
                self.runner_image, "python", "-c", _FETCH, target_url, str(timeout_seconds),
            ], max(self.command_timeout, timeout_seconds + 5))
            if runner.returncode:
                raise RuntimeError(runner.stderr.strip() or "runner failed")
            headers = json.loads(runner.stdout)
            if not isinstance(headers, dict):
                raise RuntimeError("runner returned invalid headers")
            return SandboxResult({str(k): str(v) for k, v in headers.items()}, False)
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            self._last_error = str(exc)
            raise

    def cleanup(self) -> bool:
        """Remove target and private network, and verify both no longer exist."""

        ok = True
        try:
            if self.container_id or self.target_name:
                result = self._run(["rm", "-f", self.target_name], self.command_timeout)
                ok = ok and result.returncode in (0, 1)
                self.container_id = None
            if self._network_created:
                result = self._run(["network", "rm", self.network_name], self.command_timeout)
                ok = ok and result.returncode in (0, 1)
                inspect = self._run(["network", "inspect", self.network_name], self.command_timeout)
                ok = ok and inspect.returncode != 0
                self._network_created = False
        except RuntimeError:
            ok = False
        return ok

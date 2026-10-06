"""Bounded local Docker image inspection; never build or pull images."""

import json
import subprocess

from ..core.config import settings


class ImageUnavailable(ValueError):
    """The operator must prepare the requested image on this daemon."""


class DockerUnavailable(RuntimeError):
    """Docker inspection cannot currently reach a usable daemon."""


def _command(args):
    try:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            timeout=settings.docker_timeout_seconds,
        )
    except OSError, subprocess.TimeoutExpired:
        raise DockerUnavailable("Docker image inspection unavailable") from None


def require_local_image(image):
    if settings.sandbox_backend != "docker":
        return
    result = _command(["image", "inspect", "--format", "{{.Id}}", image])
    if result.returncode:
        if _command(["info", "--format", "{{.ServerVersion}}"]).returncode:
            raise DockerUnavailable("Docker image inspection unavailable")
        raise ImageUnavailable(
            "Target image is not available locally; build or pull it first"
        )


def local_images():
    if settings.sandbox_backend != "docker":
        return []
    result = _command(["image", "ls", "--no-trunc", "--format", "{{json .}}"])
    if result.returncode:
        raise DockerUnavailable("Docker image discovery unavailable")
    try:
        items = {}
        for line in result.stdout.splitlines():
            row = json.loads(line)
            if row["Repository"] == "<none>" or row["Tag"] == "<none>":
                continue
            name = f"{row['Repository']}:{row['Tag']}"
            items[name] = {"image": name, "id": row["ID"]}
        return [items[name] for name in sorted(items)]
    except ValueError, KeyError, TypeError:
        raise DockerUnavailable("Docker returned invalid image metadata") from None

"""Authorization rules shared by API admission, execution, and recovery."""

from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

ACTOR = "local-development"


class PolicyError(ValueError):
    pass


def unexpired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value > datetime.now(timezone.utc)


def bounded_url(candidate: str, registered: str) -> bool:
    left, right = urlsplit(candidate), urlsplit(registered)
    for url in (left, right):
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.fragment
        ):
            return False

    def origin(url):
        return (
            url.scheme,
            url.hostname.lower(),
            url.port or (443 if url.scheme == "https" else 80),
        )

    try:
        if origin(left) != origin(right):
            return False
    except ValueError:
        return False
    base, path = unquote(right.path).rstrip("/") or "/", unquote(left.path) or "/"
    if (
        any(part in {".", ".."} for part in (base + "/" + path).split("/"))
        or "\\" in base + path
    ):
        return False
    # Reject multiply encoded paths rather than interpreting them differently to a target.
    if unquote(base) != base or unquote(path) != path:
        return False
    return base == "/" or path == base or path.startswith(base + "/")


def validate(project, target, scope, allowed_images: list[str]) -> None:
    if not project or project.owner_actor != ACTOR or not target or not scope:
        raise PolicyError("valid authorization scope required")
    if (
        target.project_id != project.id
        or scope.project_id != project.id
        or scope.target_id != target.id
    ):
        raise PolicyError("valid authorization scope required")
    if not unexpired(scope.expires_at) or not bounded_url(
        scope.allowed_url, target.url
    ):
        raise PolicyError("authorization expired or outside registered target")
    if target.image not in allowed_images:
        raise PolicyError("target image is not in the trusted image allowlist")

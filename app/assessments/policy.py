"""Target boundaries shared by API admission, execution, and recovery."""

from typing import Annotated
from urllib.parse import SplitResult, unquote, urlsplit, urlunsplit

from pydantic import BeforeValidator

from ..core.constraints import StoredHttpUrl
from ..core.identity import ACTOR


class PolicyError(ValueError):
    """The requested assessment is outside its registered target."""


def validate_response_url(value):
    # Check raw input before URL normalization can erase unsafe components.
    if not bounded_url(str(value), str(value)):
        raise ValueError("URL contains unsafe or ambiguous components")
    return value


ResponseUrl = Annotated[StoredHttpUrl, BeforeValidator(validate_response_url)]


def public_response_url(url):
    parsed = urlsplit(str(url))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def http_origin(url: SplitResult) -> tuple[str, str | None, int]:
    port = url.port
    if port is None:
        port = 443 if url.scheme == "https" else 80
    return url.scheme, url.hostname, port


def bounded_url(candidate: str, registered: str) -> bool:
    try:
        left, right = urlsplit(candidate), urlsplit(registered)
        for url in (left, right):
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.fragment
            ):
                return False
        if http_origin(left) != http_origin(right):
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


def validate(project, target, url: str) -> None:
    if not project or project.owner_actor != ACTOR or not target:
        raise PolicyError("valid project and target required")
    if target.project_id != project.id:
        raise PolicyError("target does not belong to this project")
    if not bounded_url(url, target.url):
        raise PolicyError("assessment URL is outside the registered target")

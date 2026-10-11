"""Shared declared-response applicability for passive browser header checks."""

from .base import CheckOutcome

_DOCUMENT_TYPES = {"text/html", "application/xhtml+xml"}
_NON_DOCUMENT_TYPES = {
    "application/json",
    "text/javascript",
    "application/javascript",
    "text/ecmascript",
    "application/ecmascript",
    "text/css",
    "text/plain",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/avif",
    "image/bmp",
    "image/tiff",
    "image/x-icon",
    "image/vnd.microsoft.icon",
}


def unevaluated_check(
    rule_id: str, status_code: int, media_type: str | None
) -> CheckOutcome | None:
    status = "skipped"
    if status_code in {301, 302, 303, 307, 308}:
        reason = "Redirect destination was not followed or assessed."
    elif status_code < 200 or status_code in {204, 205, 304}:
        reason = "No complete response representation was assessed."
    elif rule_id == "x-content-type-options" or media_type in _DOCUMENT_TYPES:
        return None
    elif media_type in _NON_DOCUMENT_TYPES or (
        media_type is not None
        and media_type.startswith("application/")
        and media_type.endswith("+json")
    ):
        reason = "Not applicable to this declared non-document media type."
    else:
        status = "inconclusive"
        reason = "Declared content type is missing, malformed, conflicting, or unsupported; document applicability is unknown."
    return CheckOutcome(rule_id=rule_id, status=status, reason=reason)

"""Shared declared-response applicability for passive browser header checks."""

from .base import CheckOutcome


def response_applicability(
    applicability: str, status_code: int, media_type: str | None
) -> tuple[str, str] | None:
    """Classify a declared representation once for admission and analysis."""
    if status_code in {301, 302, 303, 307, 308}:
        return "skipped", "Redirect destination was not followed or assessed."
    if status_code < 200 or status_code in {204, 205, 304}:
        return "skipped", "No complete response representation was assessed."
    if applicability == "representation" or media_type in _DOCUMENT_TYPES:
        return None
    if media_type in _NON_DOCUMENT_TYPES or (
        media_type is not None
        and media_type.startswith("application/")
        and media_type.endswith("+json")
    ):
        return "skipped", "Not applicable to this declared non-document media type."
    return (
        "inconclusive",
        "Declared content type is missing, malformed, conflicting, or unsupported; document applicability is unknown.",
    )


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
    result = response_applicability(
        "representation" if rule_id == "x-content-type-options" else "document",
        status_code,
        media_type,
    )
    if result is None:
        return None
    status, reason = result
    return CheckOutcome(rule_id=rule_id, status=status, reason=reason)

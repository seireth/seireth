"""Conservative checks for three browser response headers."""

import re
from dataclasses import dataclass

from .base import (
    CheckOutcome,
    HttpObservation,
    Plugin,
    PluginFinding,
    PluginManifest,
    PluginResponse,
)
from .http_security_headers_contract import (
    RULE_REQUIREMENTS,
    HeaderCondition,
    HeaderName,
)

_FRAME_HOST = re.compile(r"https?://(?:\*\.)?[a-zA-Z0-9.-]+(?::\d+)?")


def _header_values(fields: list[str]) -> list[str]:
    """Split HTTP lists while preserving quoted commas and empty values."""
    if not fields:
        return []

    text = ", ".join(fields)
    values = []
    start = 0
    quoted = escaped = False

    for position, char in enumerate(text):
        if escaped:
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            values.append(text[start:position].strip(" \t"))
            start = position + 1

    values.append(text[start:].strip(" \t"))
    return values


def _frame_ancestors(policy: str) -> list[str] | None:
    """Return the first frame-ancestors directive; later duplicates are ignored."""
    for directive in policy.split(";"):
        parts = directive.strip().split()
        if parts and parts[0].lower() == "frame-ancestors":
            return parts[1:]
    return None


def _restricts_framing(sources: list[str]) -> bool:
    """Recognize a limited subset of restrictive ancestor sources."""
    # An empty source list blocks all ancestors.
    if not sources or sources == ["'none'"]:
        return True

    return all(
        source == "'self'" or _FRAME_HOST.fullmatch(source) for source in sources
    )


@dataclass(frozen=True)
class FramingEvaluation:
    protected: bool
    header: HeaderName
    condition: HeaderCondition | None = None


def _evaluate_framing(
    headers: dict[str, list[str]],
    policies: list[str],
) -> FramingEvaluation:
    ancestors = [_frame_ancestors(policy) for policy in policies]

    if any(sources is not None for sources in ancestors):
        # Any enforced frame-ancestors directive overrides X-Frame-Options.
        # Every policy is enforced, so one restrictive policy provides protection.
        protected = any(
            _restricts_framing(sources) for sources in ancestors if sources is not None
        )
        if protected:
            return FramingEvaluation(True, "content-security-policy")
        unrestricted = any(
            source in {"*", "http:", "https:"}
            for sources in ancestors
            if sources is not None
            for source in sources
        )
        return FramingEvaluation(
            False,
            "content-security-policy",
            "unrestricted" if unrestricted else "unrecognized",
        )

    options = {
        value.lower() for value in _header_values(headers.get("x-frame-options", []))
    }

    # Conflicting values involving DENY, SAMEORIGIN, or legacy ALLOWALL fail closed.
    protected = bool(options & {"deny", "sameorigin"}) or (
        len(options) > 1 and "allowall" in options
    )
    return FramingEvaluation(
        protected,
        "x-frame-options",
        None if protected else _absent_condition(headers.get("x-frame-options", [])),
    )


_RULES = (
    (
        "x-content-type-options",
        "Missing or ineffective X-Content-Type-Options",
        "The response does not enable nosniff MIME type protection.",
        "Set X-Content-Type-Options: nosniff on the response.",
    ),
    (
        "content-security-policy",
        "Missing Content-Security-Policy",
        "The response has no nonblank enforced Content-Security-Policy header.",
        "Define and test an enforced Content-Security-Policy appropriate for this application.",
    ),
    (
        "framing-protection",
        "Missing or ineffective framing protection",
        "The response has no restrictive enforced CSP frame-ancestors value recognized by this check, or an effective X-Frame-Options fallback.",
        "Use a restrictive enforced CSP frame-ancestors directive, or set X-Frame-Options to DENY or SAMEORIGIN when that directive is absent.",
    ),
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


def _absent_condition(fields: list[str]) -> HeaderCondition:
    if not fields:
        return "missing"
    return "blank" if not any(field.strip() for field in fields) else "unrecognized"


def _unevaluated_check(
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


def analyze(observation: HttpObservation) -> PluginResponse:
    """Evaluate declared response context; never retain arbitrary header values."""
    headers, media_type = observation.headers, observation.media_type
    findings, checks = [], []
    policies = [
        policy.strip()
        for field in headers.get("content-security-policy", [])
        for policy in field.split(",")
        if policy.strip()
    ]
    for rule_id, title, description, remediation in _RULES:
        expected = RULE_REQUIREMENTS[rule_id]
        unevaluated = _unevaluated_check(rule_id, observation.status_code, media_type)
        if unevaluated is not None:
            checks.append(unevaluated)
            continue
        if rule_id == "x-content-type-options":
            header = rule_id
            condition = _absent_condition(headers.get(header, []))
            values = _header_values(headers.get(header, []))
            passed = bool(values) and values[0].lower() == "nosniff"
            passed_reason = "The first parsed value enables nosniff MIME protection."
        elif rule_id == "content-security-policy":
            header = rule_id
            condition = _absent_condition(headers.get(header, []))
            passed = bool(policies)
            passed_reason = (
                "A nonblank enforced CSP is present; the full policy is not validated."
            )
        else:
            framing = _evaluate_framing(headers, policies)
            passed, header, condition = (
                framing.protected,
                framing.header,
                framing.condition,
            )
            passed_reason = "Recognized restrictive framing protection is present."
        checks.append(
            CheckOutcome(
                rule_id=rule_id,
                status="passed" if passed else "failed",
                reason=passed_reason
                if passed
                else f"Required protection is {condition}; expected {expected}.",
            )
        )
        if not passed:
            findings.append(
                PluginFinding(
                    title=title,
                    severity="medium",
                    description=description,
                    remediation=remediation,
                    evidence={
                        "url": str(observation.url),
                        "header": header,
                        "rule_id": rule_id,
                        "status_code": observation.status_code,
                        "media_type": media_type,
                        "condition": condition,
                        "expected": expected,
                    },
                )
            )
    return PluginResponse(findings=tuple(findings), checks=tuple(checks))


PLUGIN = Plugin(
    manifest=PluginManifest(
        id="http-security-headers",
        name="HTTP security headers",
        description="Check MIME protection, CSP presence, and framing protection using declared HTTP response context.",
    ),
    analyze=analyze,
)

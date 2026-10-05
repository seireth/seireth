"""Conservative checks for three browser response headers."""

import re

from .base import (
    HttpObservation,
    Plugin,
    PluginFinding,
    PluginManifest,
    PluginResponse,
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


def _framing_protected(
    headers: dict[str, list[str]],
    policies: list[str],
) -> bool:
    ancestors = [_frame_ancestors(policy) for policy in policies]

    if any(sources is not None for sources in ancestors):
        # Any enforced frame-ancestors directive overrides X-Frame-Options.
        # Every policy is enforced, so one restrictive policy provides protection.
        return any(
            _restricts_framing(sources) for sources in ancestors if sources is not None
        )

    options = {
        value.lower() for value in _header_values(headers.get("x-frame-options", []))
    }

    # Conflicting values involving DENY, SAMEORIGIN, or legacy ALLOWALL fail closed.
    return bool(options & {"deny", "sameorigin"}) or (
        len(options) > 1 and "allowall" in options
    )


def analyze(observation: HttpObservation) -> PluginResponse:
    """Report missing or ineffective values without claiming full CSP validation."""
    url = str(observation.url)
    headers = observation.headers
    findings = []

    content_types = _header_values(headers.get("x-content-type-options", []))
    if not content_types or content_types[0].lower() != "nosniff":
        findings.append(
            PluginFinding(
                title="Missing or ineffective X-Content-Type-Options",
                severity="medium",
                description="The response does not enable nosniff MIME type protection.",
                remediation="Set X-Content-Type-Options: nosniff on the response.",
                evidence={
                    "header": "x-content-type-options",
                    "url": url,
                },
            )
        )

    policies = [
        policy.strip()
        for field in headers.get("content-security-policy", [])
        for policy in field.split(",")
        if policy.strip()
    ]
    if not policies:
        findings.append(
            PluginFinding(
                title="Missing Content-Security-Policy",
                severity="medium",
                description="The response has no nonblank enforced Content-Security-Policy header.",
                remediation="Define and test an enforced Content-Security-Policy appropriate for this application.",
                evidence={
                    "header": "content-security-policy",
                    "url": url,
                },
            )
        )

    if not _framing_protected(headers, policies):
        findings.append(
            PluginFinding(
                title="Missing or ineffective framing protection",
                severity="medium",
                description="The response has no restrictive enforced CSP frame-ancestors value recognized by this check, or an effective X-Frame-Options fallback.",
                remediation="Use a restrictive enforced CSP frame-ancestors directive, or set X-Frame-Options to DENY or SAMEORIGIN when that directive is absent.",
                evidence={
                    "header": "x-frame-options",
                    "url": url,
                },
            )
        )

    return PluginResponse(findings=tuple(findings))


PLUGIN = Plugin(
    manifest=PluginManifest(
        id="security-headers",
        name="HTTP security headers",
        description="Check three browser security headers on the target response.",
    ),
    analyze=analyze,
)

"""Conservative checks for three browser response headers."""

import re
from collections.abc import Mapping

from .base import PluginFinding


def _has_frame_ancestors(policy: str) -> bool:
    # Recognize a conservative subset rather than treating an arbitrary directive
    # value (including '*') as framing protection. Report-only is a separate header.
    host = re.compile(r"https?://(?:\*\.)?[a-zA-Z0-9.-]+(?::\d+)?")
    for directive in policy.split(";"):
        parts = directive.strip().split()
        if not parts or parts[0].lower() != "frame-ancestors":
            continue
        sources = parts[1:]
        if sources == ["'none'"] or (
            sources
            and all(source == "'self'" or host.fullmatch(source) for source in sources)
        ):
            return True
        return False
    return False


def security_headers(headers: Mapping[str, str], url: str) -> list[PluginFinding]:
    """Report missing or ineffective values without claiming full CSP validation."""

    observed = {name.lower(): value.strip() for name, value in headers.items()}
    findings = []

    content_type = observed.get("x-content-type-options", "")
    if content_type.lower() != "nosniff":
        findings.append(
            PluginFinding(
                title="Missing or ineffective X-Content-Type-Options",
                severity="medium",
                description="The response does not enable nosniff MIME type protection.",
                remediation="Set X-Content-Type-Options: nosniff on the response.",
                evidence={"header": "x-content-type-options", "url": url},
            )
        )

    policy = observed.get("content-security-policy", "")
    if not policy:
        findings.append(
            PluginFinding(
                title="Missing Content-Security-Policy",
                severity="medium",
                description="The response has no nonblank enforced Content-Security-Policy header.",
                remediation="Define and test an enforced Content-Security-Policy appropriate for this application.",
                evidence={"header": "content-security-policy", "url": url},
            )
        )

    frame_option = observed.get("x-frame-options", "").upper()
    if frame_option not in {"DENY", "SAMEORIGIN"} and not _has_frame_ancestors(policy):
        findings.append(
            PluginFinding(
                title="Missing or ineffective framing protection",
                severity="medium",
                description="The response has neither a supported X-Frame-Options value nor an enforced CSP frame-ancestors directive.",
                remediation="Set X-Frame-Options to DENY or SAMEORIGIN, or set an enforced CSP frame-ancestors directive.",
                evidence={"header": "x-frame-options", "url": url},
            )
        )

    return findings

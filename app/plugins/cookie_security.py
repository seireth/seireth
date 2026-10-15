"""Passive cookie attribute checks without retaining cookie values."""

import re
from urllib.parse import urlsplit

from .base import (
    AnalysisContext,
    CheckOutcome,
    HttpObservation,
    Plugin,
    PluginFinding,
    PluginManifest,
    PluginResponse,
)

_TOKEN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_COOKIE_VALUE = re.compile(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*")


def _parse(field: str) -> tuple[str, dict[str, str]] | None:
    """Parse one field; commas in Expires never delimit cookies."""
    if any(ord(char) < 32 and char != "\t" or ord(char) == 127 for char in field):
        return None
    parts = field.split(";")
    name, separator, value = parts[0].partition("=")
    name, value = name.strip(" \t"), value.strip(" \t")
    if not separator or not _TOKEN.fullmatch(name):
        return None
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    if not _COOKIE_VALUE.fullmatch(value):
        return None
    attributes = {}
    for part in parts[1:]:
        attribute, _, attribute_value = part.partition("=")
        attribute = attribute.strip(" \t").lower()
        if attribute not in ("secure", "httponly", "samesite", "domain", "path"):
            continue
        attribute_value = attribute_value.strip(" \t")
        # Runner headers use ISO-8859-1: each decoded character is one wire byte.
        if len(attribute_value) > 1024:
            continue
        attributes[attribute] = "" if attribute == "secure" else attribute_value
    return name, attributes


def analyze(observation: HttpObservation, context: AnalysisContext) -> PluginResponse:
    url = str(observation.url)
    https = urlsplit(url).scheme == "https"
    findings = []
    observed, session_attributes = set(), []
    for field in observation.headers.get("set-cookie", []):
        parsed = _parse(field)
        if parsed is None:
            continue
        name, attributes = parsed
        observed.add(name)
        if name in context.session_cookies:
            session_attributes.append(attributes)
            for attribute, title in (("secure", "Secure"), ("httponly", "HttpOnly")):
                if attribute not in attributes:
                    findings.append(
                        PluginFinding(
                            title=f"Declared session cookie lacks {title}",
                            severity="medium",
                            description=f"Declared session cookie {name!r} does not set {title}.",
                            remediation=f"Set {title} on this session cookie.",
                            evidence={
                                "url": url,
                                "header": "set-cookie",
                                "cookie_name": name,
                                "rule_id": f"session-cookie-{attribute}",
                                "secure": "secure" in attributes,
                                "httponly": "httponly" in attributes,
                            },
                        )
                    )
        prefix_name = name.lower()
        secure = "secure" in attributes
        evidence = {"url": url, "header": "set-cookie", "cookie_name": name}
        if attributes.get("samesite", "").lower() == "none" and not secure:
            findings.append(
                PluginFinding(
                    title="SameSite=None cookie lacks Secure",
                    severity="low",
                    description=f"Cookie {name!r} uses SameSite=None without Secure; browsers may reject this cookie.",
                    remediation="Add Secure and serve the cookie over HTTPS, or choose SameSite=Lax or Strict if cross-site use is unnecessary.",
                    evidence={
                        **evidence,
                        "rule_id": "samesite-none-without-secure",
                        "samesite": "none",
                        "secure": False,
                    },
                )
            )
        if prefix_name.startswith("__secure-") and not (secure and https):
            findings.append(
                PluginFinding(
                    title="Invalid __Secure- cookie configuration",
                    severity="low",
                    description=f"Cookie {name!r} does not satisfy the __Secure- prefix requirements; supporting browsers may reject it.",
                    remediation="Set Secure and emit this cookie from an HTTPS response.",
                    evidence={
                        **evidence,
                        "rule_id": "secure-prefix",
                        "secure": secure,
                        "https": https,
                    },
                )
            )
        domain = bool(attributes.get("domain", ""))
        root_path = attributes.get("path") == "/"
        if prefix_name.startswith("__host-") and not (
            secure and https and not domain and root_path
        ):
            findings.append(
                PluginFinding(
                    title="Invalid __Host- cookie configuration",
                    severity="low",
                    description=f"Cookie {name!r} does not satisfy the __Host- prefix requirements; supporting browsers may reject it.",
                    remediation="Emit this cookie over HTTPS with Secure and explicit Path=/, and omit Domain.",
                    evidence={
                        **evidence,
                        "rule_id": "host-prefix",
                        "secure": secure,
                        "https": https,
                        "domain_present": domain,
                        "root_path": root_path,
                    },
                )
            )
    checks = []
    for rule in ("samesite-none-without-secure", "secure-prefix", "host-prefix"):
        checks.append(
            CheckOutcome(
                rule_id=rule,
                status="failed"
                if any(item.evidence.get("rule_id") == rule for item in findings)
                else "passed"
                if observed
                else "skipped",
                reason="Observed cookies were evaluated for this attribute requirement."
                if observed
                else "No parseable response cookies were observed.",
            )
        )
    if context.session_cookies:
        for attribute in ("secure", "httponly"):
            checks.append(
                CheckOutcome(
                    rule_id=f"session-cookie-{attribute}",
                    status=(
                        "failed"
                        if any(attribute not in item for item in session_attributes)
                        else "passed"
                        if session_attributes
                        else "inconclusive"
                    ),
                    reason="Declared session cookie attributes evaluated."
                    if session_attributes
                    else "No declared session cookie was observed.",
                )
            )
    if context.expected_cookies:
        missing = set(context.expected_cookies) - observed
        checks.append(
            CheckOutcome(
                rule_id="session-cookie-present",
                status="inconclusive" if missing else "passed",
                reason="An expected cookie was not observed or could not be parsed."
                if missing
                else "All expected cookies were observed.",
            )
        )
    return PluginResponse(findings=tuple(findings), checks=tuple(checks))


PLUGIN = Plugin(
    manifest=PluginManifest(
        id="cookie-security",
        version="1.0.0",
        name="HTTP cookie security",
        description="Check SameSite=None and __Secure-/__Host- requirements on response cookies without retaining cookie values.",
    ),
    analyze=analyze,
    rules={
        "samesite-none-without-secure": "cookie-observation",
        "secure-prefix": "cookie-observation",
        "host-prefix": "cookie-observation",
        "session-cookie-secure": "session",
        "session-cookie-httponly": "session",
        "session-cookie-present": "cookie-presence",
    },
)

"""Passive cookie attribute checks without retaining cookie values."""

import re
from urllib.parse import urlsplit

from .base import (
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
        if attribute not in ("secure", "samesite", "domain", "path"):
            continue
        attribute_value = attribute_value.strip(" \t")
        # Runner headers use ISO-8859-1: each decoded character is one wire byte.
        if len(attribute_value) > 1024:
            continue
        attributes[attribute] = "" if attribute == "secure" else attribute_value
    return name, attributes


def analyze(observation: HttpObservation) -> PluginResponse:
    url = str(observation.url)
    https = urlsplit(url).scheme == "https"
    findings = []
    for field in observation.headers.get("set-cookie", []):
        parsed = _parse(field)
        if parsed is None:
            continue
        name, attributes = parsed
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
                        "rule": "samesite-none-without-secure",
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
                        "rule": "secure-prefix",
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
                        "rule": "host-prefix",
                        "secure": secure,
                        "https": https,
                        "domain_present": domain,
                        "root_path": root_path,
                    },
                )
            )
    return PluginResponse(findings=tuple(findings))


PLUGIN = Plugin(
    manifest=PluginManifest(
        id="cookie-security",
        name="HTTP cookie security",
        description="Check SameSite=None and __Secure-/__Host- requirements on response cookies without retaining cookie values.",
    ),
    analyze=analyze,
)

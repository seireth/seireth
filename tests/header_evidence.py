"""Independent header evidence setup; expected assertions remain explicit."""

_REQUIREMENTS = {
    "x-content-type-options": "nosniff",
    "content-security-policy": "nonblank enforced CSP",
    "framing-protection": "recognized restrictive framing protection",
}


def header_evidence(
    rule_id="content-security-policy",
    *,
    url="http://demo-app:8080/",
    status_code=200,
    media_type="text/html",
    condition="missing",
    header=None,
):
    return {
        "url": url,
        "header": header
        or ("x-frame-options" if rule_id == "framing-protection" else rule_id),
        "rule_id": rule_id,
        "status_code": status_code,
        "media_type": media_type,
        "condition": condition,
        "expected": _REQUIREMENTS[rule_id],
    }

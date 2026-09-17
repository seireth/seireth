from dataclasses import dataclass

from .sandbox import Sandbox


@dataclass(frozen=True)
class PluginFinding:
    """A finding returned by a security-test plugin."""

    title: str
    severity: str
    description: str
    evidence: dict


def security_headers(sandbox: Sandbox, url: str) -> list[PluginFinding]:
    """Check for baseline browser security headers without modifying the target.

    Args:
        sandbox: Backend used to obtain the target response headers.
        url: Authorized target URL included in evidence.

    Returns:
        One medium-severity finding for each missing required header.
    """

    headers = {k.lower(): v for k, v in sandbox.execute(url).headers.items()}
    required = {
        "x-content-type-options": "Missing X-Content-Type-Options header",
        "content-security-policy": "Missing Content-Security-Policy header",
        "x-frame-options": "Missing X-Frame-Options header",
    }
    return [
        PluginFinding(
            f"Missing security header: {name}",
            "medium",
            message,
            {"header": name, "url": url},
        )
        for name, message in required.items()
        if name not in headers
    ]


"""Security-test plugins and their normalized finding types."""

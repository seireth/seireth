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
    """Check browser security headers without modifying the target."""

    headers = {k.lower(): v for k, v in sandbox.execute(url).items()}
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

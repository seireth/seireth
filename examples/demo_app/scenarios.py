"""Explicit HTTP fixtures and independently specified expected plugin findings."""

from dataclasses import dataclass

IMAGE = "seireth/demo-app:local"
ORIGIN = "http://demo-app:8080"
NOSNIFF = "x-content-type-options"
CSP = "content-security-policy"
FRAMING = "framing-protection"
APPLICATION_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
PROTECTED = (
    ("X-Content-Type-Options", "nosniff"),
    ("Content-Security-Policy", APPLICATION_CSP),
)
FALLBACK = (("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"))
POLICY_ONLY = (
    ("X-Content-Type-Options", "nosniff"),
    ("Content-Security-Policy", "default-src 'self'"),
)


@dataclass(frozen=True)
class Scenario:
    path: str
    name: str
    description: str
    headers: tuple[tuple[str, str], ...]
    expected: tuple[str, ...] = ()
    status: int = 200
    cookie_rules: tuple[str, ...] = ()
    content_type: str | None = "text/html; charset=utf-8"
    media_type: str | None = "text/html"
    checks: tuple[str, str, str] | None = None

    @property
    def expected_checks(self):
        return self.checks or tuple(
            "failed" if rule in self.expected else "passed"
            for rule in (NOSNIFF, CSP, FRAMING)
        )


def framing(path, name, value, expected=(), extra=()):
    return Scenario(
        f"/lab/{path}",
        name,
        "Enforced CSP framing policy and header precedence.",
        (
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy", f"default-src 'self'; {value}"),
            *extra,
        ),
        expected,
    )


SCENARIOS = (
    Scenario(
        "/",
        "Workspace overview",
        "HTML dashboard with external CSS and JavaScript.",
        PROTECTED,
    ),
    Scenario(
        "/tickets",
        "Support tickets",
        "A working ticket list and creation form.",
        PROTECTED,
    ),
    Scenario(
        "/account",
        "Account settings",
        "A protected account page with synthetic profile data.",
        PROTECTED,
    ),
    Scenario(
        "/api/tickets",
        "Tickets JSON API",
        "A JSON response using the same application middleware.",
        PROTECTED,
        content_type="application/json; charset=utf-8",
        media_type="application/json",
        checks=("passed", "skipped", "skipped"),
    ),
    Scenario(
        "/assets/app.css",
        "Stylesheet",
        "Static resources also receive response protection.",
        PROTECTED,
        content_type="text/css; charset=utf-8",
        media_type="text/css",
        checks=("passed", "skipped", "skipped"),
    ),
    Scenario(
        "/assets/app.js",
        "Application script",
        "External JavaScript allowed by the application CSP.",
        PROTECTED,
        content_type="text/javascript; charset=utf-8",
        media_type="text/javascript",
        checks=("passed", "skipped", "skipped"),
    ),
    Scenario(
        "/login",
        "Login redirect",
        "A 303 response; checks are skipped and the scanner must not follow it.",
        (("X-Content-Type-Options", "nosniff"),),
        (),
        303,
        checks=("skipped", "skipped", "skipped"),
    ),
    Scenario(
        "/errors/not-found",
        "Unprotected 404",
        "A common error-handler middleware gap.",
        (),
        (NOSNIFF, CSP, FRAMING),
        404,
    ),
    Scenario(
        "/errors/unavailable",
        "Partial protection on 503",
        "A maintenance response missing only MIME protection.",
        (
            ("Content-Security-Policy", "default-src 'self'"),
            ("X-Frame-Options", "DENY"),
        ),
        (NOSNIFF,),
        503,
    ),
    Scenario(
        "/lab/json-unprotected",
        "JSON without document headers",
        "Only MIME protection applies to declared JSON.",
        (),
        (NOSNIFF,),
        content_type="application/json",
        media_type="application/json",
        checks=("failed", "skipped", "skipped"),
    ),
    Scenario(
        "/lab/css-unprotected",
        "CSS without document headers",
        "Only MIME protection applies to a stylesheet.",
        (),
        (NOSNIFF,),
        content_type="text/css",
        media_type="text/css",
        checks=("failed", "skipped", "skipped"),
    ),
    Scenario(
        "/lab/no-content",
        "No content",
        "A 204 response has no representation to assess.",
        (),
        (),
        204,
        checks=("skipped", "skipped", "skipped"),
    ),
    Scenario(
        "/lab/unknown-type",
        "Missing content type",
        "Document applicability is unknown.",
        (),
        (NOSNIFF,),
        content_type=None,
        media_type=None,
        checks=("failed", "inconclusive", "inconclusive"),
    ),
    Scenario(
        "/lab/malformed-type",
        "Malformed content type",
        "A malformed declared type must not be guessed.",
        (),
        (NOSNIFF,),
        content_type="invalid",
        media_type=None,
        checks=("failed", "inconclusive", "inconclusive"),
    ),
    Scenario(
        "/lab/conflicting-types",
        "Conflicting content types",
        "Different declared types leave document applicability unknown.",
        (("Content-Type", "application/json"),),
        (NOSNIFF,),
        media_type=None,
        checks=("failed", "inconclusive", "inconclusive"),
    ),
    Scenario(
        "/lab/missing-all",
        "No security headers",
        "An application route bypassing the header middleware.",
        (),
        (NOSNIFF, CSP, FRAMING),
    ),
    Scenario(
        "/lab/missing-nosniff",
        "Missing nosniff",
        "CSP protects framing, but MIME protection is absent.",
        PROTECTED[1:],
        (NOSNIFF,),
    ),
    Scenario(
        "/lab/invalid-nosniff",
        "Ineffective nosniff",
        "A misspelled value does not enable MIME protection.",
        (("X-Content-Type-Options", "invalid"), *PROTECTED[1:]),
        (NOSNIFF,),
    ),
    Scenario(
        "/lab/missing-csp",
        "Missing CSP",
        "X-Frame-Options remains an effective fallback.",
        FALLBACK,
        (CSP,),
    ),
    Scenario(
        "/lab/blank-csp",
        "Blank CSP",
        "A present but empty policy does not qualify.",
        (*FALLBACK, ("Content-Security-Policy", " ")),
        (CSP,),
    ),
    Scenario(
        "/lab/report-only",
        "Report-only policy",
        "A report-only policy does not enforce CSP or framing protection.",
        (
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy-Report-Only", APPLICATION_CSP),
        ),
        (CSP, FRAMING),
    ),
    Scenario(
        "/lab/missing-framing",
        "Missing framing directive",
        "default-src does not replace frame-ancestors.",
        POLICY_ONLY,
        (FRAMING,),
    ),
    Scenario(
        "/lab/legacy-framing",
        "Legacy ALLOW-FROM",
        "An unsupported legacy X-Frame-Options value.",
        (*POLICY_ONLY, ("X-Frame-Options", "ALLOW-FROM https://partner.example")),
        (FRAMING,),
    ),
    framing("csp-deny", "CSP blocks all framing", "frame-ancestors 'none'"),
    framing("csp-self", "CSP allows same-origin framing", "frame-ancestors 'self'"),
    framing(
        "csp-trusted",
        "CSP allows trusted framing",
        "frame-ancestors 'self' https://partner.example https://*.partner.example:8443",
    ),
    framing(
        "csp-wildcard",
        "Permissive CSP overrides DENY",
        "frame-ancestors *",
        (FRAMING,),
        (("X-Frame-Options", "DENY"),),
    ),
    framing(
        "csp-scheme", "Scheme-only framing source", "frame-ancestors https:", (FRAMING,)
    ),
    framing(
        "csp-invalid",
        "Unrecognized framing source",
        "frame-ancestors invalid-source",
        (FRAMING,),
    ),
    framing("csp-empty", "Empty framing source list", "frame-ancestors"),
    framing(
        "csp-duplicate-open-first",
        "First duplicate is permissive",
        "frame-ancestors *; frame-ancestors 'none'",
        (FRAMING,),
    ),
    framing(
        "csp-duplicate-closed-first",
        "First duplicate is restrictive",
        "frame-ancestors 'none'; frame-ancestors *",
    ),
    Scenario(
        "/lab/csp-repeated",
        "Repeated CSP fields",
        "Multiple middleware layers emit separate enforced policies.",
        (
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy", "default-src 'self'; frame-ancestors *"),
            ("Content-Security-Policy", "frame-ancestors 'none'"),
        ),
    ),
    Scenario(
        "/lab/csp-comma",
        "Combined CSP policy list",
        "A proxy combines multiple enforced policies into one field.",
        (
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy", "frame-ancestors *, frame-ancestors 'none'"),
        ),
    ),
    Scenario(
        "/lab/report-only-xfo",
        "Report-only does not override DENY",
        "Report-only framing remains advisory; X-Frame-Options still protects.",
        (*FALLBACK, ("Content-Security-Policy-Report-Only", "frame-ancestors *")),
        (CSP,),
    ),
    Scenario(
        "/lab/xfo-sameorigin",
        "Same-origin fallback",
        "A supported X-Frame-Options value without frame-ancestors.",
        (*POLICY_ONLY, ("X-Frame-Options", "SAMEORIGIN")),
    ),
    Scenario(
        "/lab/xfo-repeated",
        "Conflicting frame options",
        "Repeated SAMEORIGIN and DENY fields provide framing protection.",
        (*POLICY_ONLY, ("X-Frame-Options", "SAMEORIGIN"), ("X-Frame-Options", "DENY")),
    ),
    Scenario(
        "/lab/xfo-quoted",
        "Quoted frame option",
        "A quoted DENY token is ineffective.",
        (*POLICY_ONLY, ("X-Frame-Options", '"DENY"')),
        (FRAMING,),
    ),
    Scenario(
        "/lab/nosniff-first-valid",
        "First MIME option is valid",
        "Repeated header fields retain their wire order.",
        (*PROTECTED, ("X-Content-Type-Options", "invalid")),
    ),
    Scenario(
        "/lab/nosniff-first-invalid",
        "First MIME option is invalid",
        "A later nosniff field does not repair the first value.",
        (("X-Content-Type-Options", "invalid"), *PROTECTED),
        (NOSNIFF,),
    ),
    Scenario(
        "/lab/nosniff-comma",
        "Combined MIME option list",
        "The first comma-separated value enables nosniff.",
        (("X-Content-Type-Options", "nosniff, invalid"), *PROTECTED[1:]),
    ),
    Scenario(
        "/lab/mixed-case",
        "Mixed-case fields and values",
        "Header names and supported values are case-insensitive.",
        (
            ("x-CoNtEnT-tYpE-oPtIoNs", "NoSniff"),
            ("CONTENT-security-POLICY", "default-src 'self'"),
            ("x-FRAME-options", "sameorigin"),
        ),
    ),
)
COOKIE_SCENARIOS = (
    Scenario(
        "/cookies",
        "Cookie configuration gaps",
        "Three explicit cookie misconfigurations and three missing security headers.",
        (
            ("Set-Cookie", "theme=synthetic-theme; SameSite=Lax"),
            ("Set-Cookie", "cross_site=synthetic-cross-site; SameSite=None"),
            ("Set-Cookie", "__Secure-demo=synthetic-secure-prefix"),
            (
                "Set-Cookie",
                "__Host-demo=synthetic-host-prefix; Secure; Domain=demo-app; Path=/app",
            ),
        ),
        (NOSNIFF, CSP, FRAMING),
        cookie_rules=("samesite-none-without-secure", "secure-prefix", "host-prefix"),
    ),
    Scenario(
        "/cookies/protected",
        "Protected cookies",
        "Protected headers and a cookie with no explicit security violations.",
        (*PROTECTED, ("Set-Cookie", "theme=synthetic-theme; SameSite=Lax")),
    ),
)
SLOW = Scenario(
    "/slow",
    "Slow response",
    "Cancellation and crash recovery fixture.",
    (),
    (NOSNIFF, CSP, FRAMING),
)
BY_PATH = {
    scenario.path: scenario for scenario in (*SCENARIOS, *COOKIE_SCENARIOS, SLOW)
}

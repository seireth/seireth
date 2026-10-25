"""Closed, value-free CSP finding vocabulary shared with public evidence."""

from typing import Literal

MAX_CSP_BYTES = 64 * 1024
MAX_CSP_FIELDS = 32
MAX_CSP_POLICIES = 32
MAX_CSP_DIRECTIVES = 128
MAX_CSP_TOKENS = 256

type CspRuleId = Literal["csp-script-sources", "csp-inline-scripts", "csp-eval"]
type CspContext = Literal["network-script", "inline-script", "script-attribute", "eval"]
type CspDirective = Literal[
    "script-src-elem", "script-src-attr", "script-src", "default-src"
]
type CspCondition = Literal[
    "missing-directive",
    "wildcard-source",
    "http-scheme-source",
    "https-scheme-source",
    "global-host-source",
    "unsafe-inline",
    "unsafe-eval",
]

RULE_CONTEXTS: dict[CspRuleId, tuple[CspContext, ...]] = {
    "csp-script-sources": ("network-script",),
    "csp-inline-scripts": ("inline-script", "script-attribute"),
    "csp-eval": ("eval",),
}
CONTEXT_DIRECTIVES: dict[CspContext, tuple[CspDirective, ...]] = {
    "network-script": ("script-src-elem", "script-src", "default-src"),
    "inline-script": ("script-src-elem", "script-src", "default-src"),
    "script-attribute": ("script-src-attr", "script-src", "default-src"),
    "eval": ("script-src", "default-src"),
}
CONTEXT_CONDITIONS: dict[CspContext, frozenset[str]] = {
    "network-script": frozenset(
        {
            "missing-directive",
            "wildcard-source",
            "http-scheme-source",
            "https-scheme-source",
            "global-host-source",
        }
    ),
    "inline-script": frozenset({"missing-directive", "unsafe-inline"}),
    "script-attribute": frozenset({"missing-directive", "unsafe-inline"}),
    "eval": frozenset({"missing-directive", "unsafe-eval"}),
}

"""Shared rule metadata for HTTP security header analysis and public evidence."""

from typing import Literal

type HeaderRuleId = Literal[
    "x-content-type-options", "content-security-policy", "framing-protection"
]
type HeaderName = Literal[
    "x-content-type-options", "content-security-policy", "x-frame-options"
]
type HeaderCondition = Literal["missing", "blank", "unrecognized", "unrestricted"]
type HeaderRequirement = Literal[
    "nosniff", "nonblank enforced CSP", "recognized restrictive framing protection"
]

RULE_REQUIREMENTS: dict[HeaderRuleId, HeaderRequirement] = {
    "x-content-type-options": "nosniff",
    "content-security-policy": "nonblank enforced CSP",
    "framing-protection": "recognized restrictive framing protection",
}

_COMMON_CONDITIONS = frozenset({"missing", "blank", "unrecognized"})
EVIDENCE_CONDITIONS: dict[tuple[HeaderRuleId, HeaderName], frozenset[str]] = {
    ("x-content-type-options", "x-content-type-options"): _COMMON_CONDITIONS,
    ("content-security-policy", "content-security-policy"): _COMMON_CONDITIONS,
    ("framing-protection", "x-frame-options"): _COMMON_CONDITIONS,
    ("framing-protection", "content-security-policy"): frozenset(
        {"unrecognized", "unrestricted"}
    ),
}

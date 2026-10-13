"""Bounded CSP3 header checks; no document content or header values are retained."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from .base import (
    AnalysisContext,
    CheckOutcome,
    HttpObservation,
    Plugin,
    PluginFinding,
    PluginManifest,
    PluginResponse,
)
from .csp_policy_contract import (
    CONTEXT_DIRECTIVES,
    MAX_CSP_BYTES,
    MAX_CSP_DIRECTIVES,
    MAX_CSP_FIELDS,
    MAX_CSP_POLICIES,
    MAX_CSP_TOKENS,
    RULE_CONTEXTS,
    CspCondition,
    CspContext,
    CspDirective,
    CspRuleId,
)
from .response_context import unevaluated_check

_SPACE = " \t\n\r\f"
_TOKEN = re.compile(r"[^ \t\n\r\f]+")
_NAME = re.compile(r"[a-zA-Z0-9-]+")
_NONCE_HASH = re.compile(r"'(?ai:nonce|sha256|sha384|sha512)-[a-zA-Z0-9+/_-]+={0,2}'")
_SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")
_HOST = re.compile(
    r"(?:(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*)://)?"
    r"(?P<host>\*|(?:\*\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*)"
    r"(?P<port>:\*|:[0-9]+)?"
    r"(?P<path>/(?:[a-zA-Z0-9\-._~!$&'()*+=:@/]|%[0-9a-fA-F]{2})*)?"
)
_RELEVANT = {
    "script-src-elem",
    "script-src-attr",
    "script-src",
    "default-src",
    "sandbox",
    "require-trusted-types-for",
}
_LIMIT_REASON = "CSP input exceeds supported analysis limits; no policy was certified."
_ABSENT_REASON = "No nonblank enforced CSP is present to analyze; the baseline header check covers absence."


class _LimitExceeded(Exception):
    """Never includes untrusted input."""


def _segments(text: str, delimiter: str) -> Iterator[str]:
    start = 0
    while True:
        end = text.find(delimiter, start)
        if end == -1:
            yield text[start:]
            return
        yield text[start:end]
        start = end + 1


def _parse(fields: list[str]) -> list[dict[str, tuple[str, ...]]]:
    if len(fields) > MAX_CSP_FIELDS:
        raise _LimitExceeded
    size = 0
    for field in fields:
        if len(field) > MAX_CSP_BYTES - size:
            raise _LimitExceeded
        try:
            size += len(field.encode("utf-8"))
        except UnicodeEncodeError:
            raise _LimitExceeded from None
        if size > MAX_CSP_BYTES:
            raise _LimitExceeded
    policies = []
    for field in fields:
        for serialized in _segments(field, ","):
            if not serialized.strip(_SPACE):
                continue
            if len(policies) == MAX_CSP_POLICIES:
                raise _LimitExceeded
            policy = {}
            directive_count = 0
            for directive in _segments(serialized, ";"):
                tokens = _TOKEN.finditer(directive)
                first = next(tokens, None)
                if first is None:
                    continue
                directive_count += 1
                if directive_count > MAX_CSP_DIRECTIVES:
                    raise _LimitExceeded
                name = first[0]
                # Browsers discard the whole non-ASCII directive. Its ignored
                # tokens still count toward the analysis budgets below.
                recognized = directive.isascii() and bool(_NAME.fullmatch(name))
                name = name.lower()
                retain = recognized and name in _RELEVANT and name not in policy
                values = []
                for count, token in enumerate(tokens, start=1):
                    if count > MAX_CSP_TOKENS:
                        raise _LimitExceeded
                    if retain:
                        values.append(token[0])
                if retain:
                    policy[name] = tuple(values)
            policies.append(policy)
    return policies


@dataclass(frozen=True)
class _Decision:
    state: Literal["allowed", "restricted", "unknown"]
    directive: CspDirective | None = None
    condition: CspCondition | None = None


def _network(sources: tuple[str, ...], directive: CspDirective) -> _Decision:
    keywords = {source.lower() for source in sources}
    if "'strict-dynamic'" in keywords:
        return _Decision("restricted", directive)
    unknown = False
    for source in sources:
        lower = source.lower()
        if source == "*":
            return _Decision("allowed", directive, "wildcard-source")
        if _SCHEME.fullmatch(source):
            if lower in {"http:", "https:"}:
                return _Decision("allowed", directive, lower[:-1] + "-scheme-source")
            unknown = True
        elif match := _HOST.fullmatch(source):
            scheme, host, port, path = (
                match["scheme"],
                match["host"],
                match["port"],
                match["path"],
            )
            if host == "*":
                if (
                    scheme
                    and scheme.lower() in {"http", "https"}
                    and not port
                    and not path
                ):
                    return _Decision("allowed", directive, "global-host-source")
                unknown = True
            elif scheme and scheme.lower() not in {"http", "https"}:
                unknown = True
        # Nonces, hashes, recognized keywords, and invalid sources do not add
        # unrestricted network permissions. Specific hosts are outside this rule.
    return _Decision("unknown" if unknown else "restricted", directive)


def _effective_sources(
    policy: dict[str, tuple[str, ...]], context: CspContext
) -> tuple[CspDirective | None, tuple[str, ...]]:
    directive = next(
        (name for name in CONTEXT_DIRECTIVES[context] if name in policy), None
    )
    return directive, policy[directive] if directive else ()


def _evaluate(
    policy: dict[str, tuple[str, ...]],
    context: CspContext,
    *,
    trusted_types_required: bool,
    trusted_types_eval: bool,
) -> _Decision:
    if "sandbox" in policy and "allow-scripts" not in {
        value.lower() for value in policy["sandbox"]
    }:
        return _Decision("restricted")
    directive, sources = _effective_sources(policy, context)
    keywords = {source.lower() for source in sources}
    if context == "eval":
        permits_eval = directive is None or "'unsafe-eval'" in keywords
        if trusted_types_eval or (trusted_types_required and permits_eval):
            return _Decision("unknown", directive)
        if permits_eval:
            return _Decision(
                "allowed",
                directive,
                "unsafe-eval" if directive else "missing-directive",
            )
        return _Decision("restricted", directive)
    if directive is None:
        return _Decision("allowed", condition="missing-directive")
    if context == "network-script":
        return _network(sources, directive)
    if "'strict-dynamic'" in keywords or any(_NONCE_HASH.fullmatch(s) for s in sources):
        return _Decision("restricted", directive)
    if "'unsafe-inline'" in keywords:
        return _Decision("allowed", directive, "unsafe-inline")
    return _Decision("restricted", directive)


@dataclass(frozen=True)
class _Rule:
    id: CspRuleId
    title: str
    severity: str
    description: str
    remediation: str
    failed_reason: str
    passed_reason: str
    unknown_reason: str


_RULES = (
    _Rule(
        "csp-script-sources",
        "Broad CSP network script sources",
        "medium",
        "The observed CSP headers permit parser-inserted scripts from arbitrary HTTP(S) origins without nonce or integrity authorization. Document content and meta-delivered policies were not inspected; this does not establish an exploitable vulnerability.",
        "Restrict script sources to application-specific origins, or deploy and test a nonce/hash policy with strict-dynamic. Audit trusted script loaders separately.",
        "The observed CSP headers permit parser-inserted scripts from arbitrary HTTP(S) origins without nonce or integrity authorization.",
        "No covered weakness identified: CSP headers restrict broad network sources for parser-inserted scripts.",
        "Supported header analysis cannot establish whether all policies permit broad network script sources.",
    ),
    _Rule(
        "csp-inline-scripts",
        "Unrestricted CSP inline script execution",
        "medium",
        "The observed CSP headers permit arbitrary inline script elements or event handlers in the reported contexts. Document content and meta-delivered policies were not inspected.",
        "Define an enforced script policy that restricts inline execution; remove unsafe-inline where present. Use external scripts or tested nonces/hashes, and replace inline event handlers with registered listeners.",
        "The observed CSP headers permit arbitrary inline script elements or event handlers in the reported contexts.",
        "No covered weakness identified: CSP headers restrict arbitrary inline script elements and event handlers.",
        "Supported header analysis cannot establish whether all policies permit arbitrary inline script execution.",
    ),
    _Rule(
        "csp-eval",
        "Unrestricted CSP JavaScript evaluation",
        "low",
        "The observed CSP headers permit unrestricted JavaScript string evaluation. This does not establish that the application evaluates attacker-controlled input.",
        "Define an enforced script-src or default-src policy that restricts JavaScript string evaluation; remove unsafe-eval where present. Replace string-based eval, Function constructors, and timers with supported alternatives.",
        "The observed CSP headers permit unrestricted JavaScript string evaluation.",
        "No covered weakness identified: CSP headers restrict unrestricted JavaScript string evaluation.",
        "Supported header analysis cannot establish unrestricted evaluation permissions in the presence of Trusted Types interactions.",
    ),
)


def analyze(observation: HttpObservation, context: AnalysisContext) -> PluginResponse:
    media_type = observation.media_type
    unevaluated = [
        unevaluated_check(rule.id, observation.status_code, media_type)
        for rule in _RULES
    ]
    if unevaluated[0] is not None:
        return PluginResponse(findings=(), checks=tuple(unevaluated))
    try:
        policies = _parse(observation.headers.get("content-security-policy", []))
    except _LimitExceeded:
        return PluginResponse(
            findings=(),
            checks=tuple(
                CheckOutcome(
                    rule_id=rule.id, status="inconclusive", reason=_LIMIT_REASON
                )
                for rule in _RULES
            ),
        )
    if not policies:
        return PluginResponse(
            findings=(),
            checks=tuple(
                CheckOutcome(rule_id=rule.id, status="skipped", reason=_ABSENT_REASON)
                for rule in _RULES
            ),
        )
    # Trusted Types requirements affect the document across all enforced policies.
    trusted_types_required = any(
        "'script'"
        in {value.lower() for value in policy.get("require-trusted-types-for", ())}
        for policy in policies
    )
    # Browser Trusted Types eval handling can bypass other policies' source-list
    # restrictions. Keep that document-wide interaction unknown; sandbox above
    # still conclusively restricts execution.
    trusted_types_eval = trusted_types_required and any(
        "'trusted-types-eval'"
        in {source.lower() for source in _effective_sources(policy, "eval")[1]}
        for policy in policies
    )
    checks, findings = [], []
    for rule in _RULES:
        observations = []
        uncertain = False
        for context in RULE_CONTEXTS[rule.id]:
            decisions = [
                _evaluate(
                    policy,
                    context,
                    trusted_types_required=trusted_types_required,
                    trusted_types_eval=trusted_types_eval,
                )
                for policy in policies
            ]
            if any(item.state == "restricted" for item in decisions):
                continue
            if any(item.state == "unknown" for item in decisions):
                uncertain = True
                continue
            observations.extend(
                {
                    "policy_index": index,
                    "context": context,
                    "directive": item.directive,
                    "condition": item.condition,
                }
                for index, item in enumerate(decisions, start=1)
            )
        status = "failed" if observations else "inconclusive" if uncertain else "passed"
        checks.append(
            CheckOutcome(
                rule_id=rule.id,
                status=status,
                reason=(
                    rule.failed_reason
                    if observations
                    else rule.unknown_reason
                    if uncertain
                    else rule.passed_reason
                ),
            )
        )
        if observations:
            findings.append(
                PluginFinding(
                    title=rule.title,
                    severity=rule.severity,
                    description=rule.description,
                    remediation=rule.remediation,
                    evidence={
                        "url": str(observation.url),
                        "header": "content-security-policy",
                        "rule_id": rule.id,
                        "status_code": observation.status_code,
                        "media_type": media_type,
                        "policy_count": len(policies),
                        "observations": observations,
                    },
                )
            )
    return PluginResponse(findings=tuple(findings), checks=tuple(checks))


PLUGIN = Plugin(
    manifest=PluginManifest(
        id="csp-policy",
        version="1.0.0",
        name="CSP policy",
        description="Analyze existing enforced CSP headers for broad script sources, unrestricted inline scripts, and JavaScript evaluation; document content is not inspected.",
    ),
    analyze=analyze,
    rules={rule: "document" for rule in RULE_CONTEXTS},
)

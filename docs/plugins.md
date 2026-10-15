# Plugin development

Only reviewed, explicitly registered modules bundled with SEIRETH load. Plugins
are trusted executable code with API process privileges. See
[Assessments](assessments.md#register-and-select) for client selection.

## Add a bundled plugin

Create a behavior-specific module under `app/plugins` exporting `PLUGIN`:

```python
from app.plugins.base import (
    AnalysisContext,
    CheckOutcome,
    HttpObservation,
    Plugin,
    PluginManifest,
    PluginResponse,
)


def analyze(observation: HttpObservation, context: AnalysisContext) -> PluginResponse:
    # Replace this placeholder with a bounded check of the observation.
    return PluginResponse(
        findings=(),
        checks=(
            CheckOutcome(
                rule_id="example-rule",
                status="inconclusive",
                reason="Example analysis has not been implemented.",
            ),
        ),
    )


PLUGIN = Plugin(
    manifest=PluginManifest(
        id="example-check",
        name="Example check",
        description="Explain the response behavior this plugin checks.",
    ),
    analyze=analyze,
    rules={"example-rule": "representation"},
)
```

Import it in `app/plugins/registry.py` and add it to the registry's ordered
`plugins` tuple. Registration enables explicit selection, never automatic
execution. Startup rejects duplicate IDs and invalid manifests.

Declare implemented rule IDs and applicability in `Plugin.rules`; the registered
metadata supplies `/api/v1/plugins` and route coverage. Derive IDs from the
plugin's existing evidence contract where possible. Applicability is
`representation`, `document`, `cookie-observation`, `session`, or `cookie-presence`.

## Contract and tests

Observation `headers` is a `dict[str, list[str]]`: names are lowercased,
differently cased names merge, and values retain response order. Do not join
repeated `Set-Cookie` fields or split them on commas, which also occur in cookie
expiry dates. Each executor returns an `HttpObservation` containing
the original authorized URL and a required integer `status_code` (100–599).
`media_type` is derived from the ordered `Content-Type` fields: parameters and
case are ignored, while missing, malformed, or conflicting declarations return
`None`. Docker's internal `target` alias is only used for the runner request.
Response bodies are not read or retained. For redirects and request configuration,
see [workflows](workflows.md#declare-the-release-coverage).

See the [header checks](assessments.md#header-checks) and
[cookie checks](assessments.md#cookie-checks) and
[CSP policy checks](assessments.md#csp-policy-checks) for built-in behavior. Their
[implementations](../app/plugins/) and [tests](../tests/plugins/) cover exact parsing
and boundary cases.

Use the analyzer signature shown above. Each plugin receives an independent
observation copy and an immutable context, and returns explicit `findings` and
`checks` tuples. Checks require unique stable rule IDs, a `passed`, `failed`,
`skipped`, or `inconclusive` status, and a short nonblank reason. Include outcomes
for rules that produce no finding.

Never put cookie values, complete cookie fields, raw CSP policies, nonces,
hashes, allowlist hosts, reporting destinations, or arbitrary attribute values in
output or diagnostics. Observation validation errors omit input values; sandbox
validation suppresses raw exception chains.

For a new evidence format, update these together:

- The models in `app/plugins/evidence.py` and API retrieval tests in
  `tests/api/test_assessments.py`.
- `EvidenceData` in `app/dashboard/src/api/types.ts` and rendering in
  `app/dashboard/src/components/EvidenceDetails.tsx`, with component tests.

The [evidence endpoint](assessments.md#retrieve-evidence) rejects fields outside its
accepted models. All evidence uses `rule_id`; registration alone does not extend that contract.

Analyzers run synchronously. Cancellation and deadline checks occur between
calls; a blocking analyzer delays interruption and cleanup. Keep analysis bounded.

Set the manifest's `version` to a numeric `major.minor.patch` value and increment
it when analysis behavior changes. The worker records the selected versions
before execution; reports read those saved versions, including when a plugin
fails. Queued plans reject a changed installed version; the rule catalogue exposes current versions.

Cover positive, negative, boundary, and relevant malformed/incomplete observations.
Use a local `PluginRegistry` to test catalog visibility and selection; preserve
shared registry/contract conformance. Follow [Contributing](../CONTRIBUTING.md#tests)
for dependencies, disposable database setup, and test commands.

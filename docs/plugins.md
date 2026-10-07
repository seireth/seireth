# Plugin development

Plugins are executable code. Only reviewed, explicitly registered modules bundled
with SEIRETH load; copying files into `app/plugins` is insufficient. External
execution and dynamic installation await isolation from API Docker-socket and
database access. For catalog-driven client selection, see
[Assessments](assessments.md#authorize-and-select).

## Add a bundled plugin

Create a behavior-specific module under `app/plugins` exporting `PLUGIN`:

```python
from .base import HttpObservation, Plugin, PluginManifest, PluginResponse


def analyze(observation: HttpObservation) -> PluginResponse:
    return PluginResponse(findings=())


PLUGIN = Plugin(
    manifest=PluginManifest(
        id="example-check",
        name="Example check",
        description="Explain the response behavior this plugin checks.",
    ),
    analyze=analyze,
)
```

Import it in `app/plugins/registry.py` and add it to the registry's ordered
`plugins` tuple. Registration enables explicit selection, never automatic
execution. Startup rejects duplicate IDs and invalid manifests.

## Contract and tests

Observation `headers` is a `dict[str, list[str]]`: names are lowercased,
differently cased names merge, and values retain response order. Do not join
repeated `Set-Cookie` fields or split them on commas, which also occur in cookie
expiry dates. Each sandbox validates and returns an `HttpObservation` containing
the original authorized URL and a required integer `status_code` (100–599).
`media_type` is derived from the ordered `Content-Type` fields: parameters and
case are ignored, while missing, malformed, or conflicting declarations return
`None`. Docker's internal `target` alias is only used for the runner request.
Redirects are not followed, and response bodies are not read or retained. The
simulated backend defaults to HTTP 200 with `text/html`.

See the [header checks](assessments.md#header-checks) and
[cookie checks](assessments.md#cookie-checks) for built-in behavior. Their
[implementations](../app/plugins/) and [tests](../tests/plugins/) cover exact parsing
and boundary cases.

Each analyzer receives an independent copy of the shared HTTP observation and
returns `PluginResponse`. Its optional `checks` tuple contains unique stable
`rule_id` values, a `passed`, `failed`, `skipped`, or `inconclusive` status, and a
short nonblank reason. The header plugin reports every check, including those
that produce no finding; cookie output remains unchanged. Titles and severities have length limits; descriptions
and remediation must contain non-whitespace text, and evidence must be
JSON-compatible. Accepted text retains its formatting. Invalid output fails the
affected assessment without partial persistence.

Never put cookie values, complete cookie fields, or arbitrary attribute values in
output or diagnostics. Observation validation errors omit input values; sandbox
validation suppresses raw exception chains.

For a new evidence format, update these together:

- The payload models accepted by `EvidenceOut` in `app/api/schemas.py` and API
  retrieval tests in `tests/api/test_assessments.py`.
- `EvidenceData` in `app/dashboard/src/api/types.ts` and rendering in
  `app/dashboard/src/components/EvidenceDetails.tsx`, with component tests.

The [evidence endpoint](assessments.md#retrieve-evidence) rejects fields outside its
accepted models; registration alone does not extend that contract.

Analyzers run synchronously. Cancellation and deadline checks occur between
calls; a blocking analyzer delays interruption and cleanup. Keep analysis bounded.

Cover positive, negative, boundary, and relevant malformed/incomplete observations.
Use a local `PluginRegistry` to test catalog visibility and selection; preserve
shared registry/contract conformance. Follow [Contributing](../CONTRIBUTING.md#tests)
for dependencies, disposable database setup, and test commands.

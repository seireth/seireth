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

Import it in `app/plugins/__init__.py` and add it to the registry's ordered
`plugins` tuple. Registration enables explicit selection, never automatic
execution. Startup rejects duplicate IDs and invalid manifests.

## Contract and tests

Observation `headers` is a `dict[str, list[str]]`: names are lowercased,
differently cased names merge, and values retain response order. Do not join
repeated `Set-Cookie` fields or split them on commas, which also occur in cookie
expiry dates. The security-header plugin inspects the last value of each checked
header. Each sandbox validates and returns an `HttpObservation` containing the
original authorized URL. Docker's internal `target` alias is only used for the
runner request. The orchestrator reuses this validated observation.

Each analyzer receives an independent copy of the shared HTTP observation and
returns `PluginResponse`. Findings require bounded title/severity, nonblank
description/remediation, and JSON-compatible evidence. Whitespace-only finding
text is rejected; accepted text retains its formatting. Invalid output fails the
affected assessment without partial persistence.

The cookie plugin retains only names, rule IDs, and normalized requirement values
or booleans in findings/evidence. Never put cookie values, complete cookie fields,
or arbitrary attribute values in output or diagnostics. Observation validation
errors omit input values; sandbox validation suppresses raw exception chains.

For a new evidence format, extend `EvidenceOut` in `app/schemas.py` and add
retrieval tests. The [evidence endpoint](assessments.md#retrieve-evidence) rejects
fields outside those models.

Analyzers run synchronously. Cancellation and deadline checks occur between
calls; a blocking analyzer delays interruption and cleanup. Keep analysis bounded.

Cover positive, negative, boundary, and relevant malformed/incomplete observations.
Use a local `PluginRegistry` to test catalog visibility and selection; preserve
shared registry/contract conformance. Run `python -m app test` and the
[Ruff checks](../CONTRIBUTING.md#development-setup).

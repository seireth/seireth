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
execution. Startup rejects duplicate IDs, invalid manifests, and unsupported
contract versions.

## Contract and tests

Each analyzer receives an independent copy of the shared HTTP observation and
returns `PluginResponse`. Findings require bounded title/severity, nonblank
description/remediation, and JSON-compatible evidence. Whitespace-only finding
text is rejected; accepted text retains its formatting. Invalid output fails the
affected assessment without partial persistence.

Cover positive, negative, boundary, and relevant malformed/incomplete observations.
Use a local `PluginRegistry` to test catalog visibility and selection; preserve
shared registry/contract conformance. Run `python -m app test` and the
[Ruff checks](../CONTRIBUTING.md#development-setup).

# Roadmap

Future directions, not release promises. See the [README](../README.md) and
[architecture](architecture.md) for implemented capabilities.

## Next priorities

1. Add passive checks and deepen finding explanations and remediation.
2. Define supported authentication/deployment before enabling multiple users.
3. Extend the versioned JSON and offline HTML assessment reports when concrete
   consumers need additional formats, while retaining evidence redaction rules.

## Later directions

- Distributed processing when concurrency requires it.
- Finding assignment, remediation, and retesting workflows.
- SARIF/PDF exports, dependency/container analysis, and external scanners.
- Stronger isolation beyond trusted local demo images.
- Administrator-controlled installation of isolated third-party plugins.
- Configurable standards mappings, separate from findings: evidence collection,
  not compliance certification.

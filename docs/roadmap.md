# Roadmap

Future directions, not release promises. See the [README](../README.md) and
[architecture](architecture.md) for implemented capabilities.

## Next priorities

1. Add passive checks and deepen finding explanations and remediation.
2. Define supported authentication/deployment before enabling multiple users.
3. Build a local web interface using findings and evidence retrieval, then add
   reports with stable schemas and redaction rules.

## Later directions

- Distributed processing when concurrency requires it.
- Finding assignment, remediation, and retesting workflows.
- SARIF/HTML exports, dependency/container analysis, and external scanners.
- Stronger isolation beyond trusted local demo images.
- Administrator-controlled installation of isolated third-party plugins.
- Configurable standards mappings, separate from findings: evidence collection,
  not compliance certification.

# Roadmap

Future directions, not release promises. See the [README](../README.md) and
[architecture](architecture.md) for implemented capabilities; historical proposals
remain in Git history.

## Next priorities

1. Extend failure-path coverage alongside new execution capabilities.
2. Add passive checks and deepen finding explanations and remediation.
3. Define supported authentication/deployment before enabling multiple users.
4. Expose evidence and reports with stable schemas and redaction rules.

## Later directions

- Distributed processing when concurrency requires it.
- Web interface, finding assignment, remediation, and retesting workflows.
- SARIF/HTML exports, dependency/container analysis, and external scanners.
- Stronger isolation beyond trusted local demo images.
- Administrator-controlled installation of isolated third-party plugins.
- Configurable standards mappings, separate from findings: evidence collection,
  not compliance certification.

Redis/Dramatiq, a Go sandbox service, and Next.js are possible future choices,
not current dependencies. PostgreSQL is already implemented.

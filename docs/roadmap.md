# Roadmap

This page separates implemented MVP behavior from future work. Future entries
are directions, not release promises or claims of existing support.

## Implemented

- Python 3.14 FastAPI application with SQLite persistence.
- Project and target registration with a server-controlled image allowlist.
- Origin-, path-, and time-bounded authorization scopes.
- Background passive assessments, cooperative cancellation, and JSON outcomes.
- A three-header presence-check plugin with findings and stored evidence.
- Simulated and Docker-backed execution, resource restrictions, and cleanup status.
- Project audit events and an executable demo-verification workflow.
- Unit/API tests, formatting and lint checks, Docker lifecycle CI, and dependency auditing.

## Next priorities

1. Strengthen execution-time policy checks, cancellation, crash recovery, and
   independent verification of every sandbox resource's removal.
2. Add more passive checks and improve finding explanations and remediation guidance.
3. Define a supported authentication/deployment model before enabling multiple users.
4. Expose useful evidence and reports with stable schemas and redaction rules.

## Later directions

- Durable job processing and a server database when concurrency requires them.
- A web interface, finding assignment, remediation, and retesting workflows.
- SARIF/HTML exports, dependency/container analysis, and external scanner integrations.
- Stronger isolation options for workloads beyond trusted local demo images.
- Configurable standards mappings, clearly separated from security findings.

Earlier designs proposed PostgreSQL, Redis/Dramatiq, a Go sandbox service, and
Next.js. These are not current dependencies or committed implementation choices.
Detailed historical proposals remain available in Git history. Any future
standards mapping would support evidence collection, not certify compliance.

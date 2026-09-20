# Roadmap

This page separates implemented MVP behavior from future work. Future entries
are directions, not release promises or claims of existing support.

## Implemented

- Python 3.14 FastAPI application with PostgreSQL 18 persistence and versioned Alembic migrations.
- Project and target registration with a server-controlled image allowlist.
- Origin-, path-, and time-bounded authorization scopes.
- Background passive assessments, interruptible cancellation/deadlines, and JSON outcomes.
- A selectable three-header plugin with limited value checks, remediation guidance,
  findings, and stored evidence.
- Simulated and Docker-backed execution, ownership labels, and independent cleanup verification.
- Project audit events and an executable demo-verification workflow.
- Unit/API tests, formatting and lint checks, Docker lifecycle CI, and dependency auditing.

## Next priorities

1. Extend failure-path coverage as additional execution capabilities are introduced.
2. Add more passive checks and deepen finding explanations and remediation guidance.
3. Define a supported authentication/deployment model before enabling multiple users.
4. Expose useful evidence and reports with stable schemas and redaction rules.

## Later directions

- Distributed job processing when concurrency requires it.
- A web interface, finding assignment, remediation, and retesting workflows.
- SARIF/HTML exports, dependency/container analysis, and external scanner integrations.
- Stronger isolation options for workloads beyond trusted local demo images.
- Configurable standards mappings, clearly separated from security findings.

PostgreSQL is implemented. Redis/Dramatiq, a Go sandbox service, and Next.js remain
possible future choices, not current dependencies.
Detailed historical proposals remain available in Git history. Any future
standards mapping would support evidence collection, not certify compliance.

# Architecture

SEIRETH MVP-0 is one Python 3.14 application using FastAPI, SQLAlchemy, SQLite,
and a process-local thread pool. There is no separate queue service, frontend,
Go service, or distributed worker in the current implementation.

## Request and execution flow

1. FastAPI validates project ownership and accepts a registered target and scope.
2. Assessment creation stores a queued record and audit event, submits work to
   the dispatcher, and returns `202 Accepted` with a `Location` header.
3. The dispatcher loads the target and scope in a separate database session.
4. The orchestrator selects the configured sandbox and runs the header plugin.
5. Findings and evidence are added; cleanup runs after plugin execution.
6. The worker commits the final state, result, and terminal audit event.

The dispatcher uses two worker threads. Startup attempts to recover persisted
queued/running assessments. It is not a durable distributed queue, and restart
recovery is not a guarantee that earlier Docker resources were reclaimed.
Use one API process for this MVP.

## Components

| Component | Responsibility |
| --- | --- |
| `app/main.py` and `app/schemas.py` | HTTP routes, request validation, scope checks, and response schemas |
| `app/models.py`, `app/db.py`, `app/migration.py` | SQLAlchemy records, sessions, and small idempotent startup migrations |
| `app/worker.py` | Background dispatch, cancellation signals, and outcome persistence |
| `app/orchestrator.py` | Plugin execution, findings/evidence, and cleanup outcomes |
| `app/sandbox.py` | Simulated backend and Docker CLI resource lifecycle |
| `app/plugins.py` | Passive presence checks for three HTTP security headers |
| `app/verify.py` | Public API workflow verification with bounded polling |

## Stored data

Projects own targets and authorization scopes. Assessments reference a project,
target, and scope, and carry status plus an optional JSON result. Findings and
evidence belong to assessments. Audit events record project actions.

The default database is `seireth.db` in the working directory. Compose stores
SQLite under `/data` in a named volume. Tests use a disposable SQLite database.
Evidence is stored internally; the public results endpoint currently exposes
normalized findings, not a standalone evidence export API.

## Sandbox backends

`inmemory` returns deterministic headers without network traffic. It is useful
for development and tests, but does not measure target security.

`docker` starts an allowlisted image on an internal per-assessment network,
then starts a Python runner on that network to fetch response headers. The
registered URL's host is mapped to the target container's network alias.
This checks the disposable image instance rather than the original remote host.

See the [security model](security-model.md) for limitations and the
[roadmap](roadmap.md) for planned capabilities.

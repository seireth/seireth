# Architecture

SEIRETH is one Python 3.14 FastAPI application with synchronous SQLAlchemy/Psycopg
and PostgreSQL 18. Its process-local dispatcher has two assessment worker threads,
plus separate ownership monitoring and cleanup reconciliation threads.

`app/main.py` assembles FastAPI, dispatcher lifespan, health, and built GUI
serving. `app/api/` groups resource routes and shared HTTP authorization;
`app/dashboard/` contains the React/TypeScript frontend and its tests.
Native and Docker servers use `app.main:app`.

`app/core/` contains configuration and shared constraints. `app/persistence/`
contains database sessions, models, and Alembic migrations. `app/assessments/`
contains policy, execution, workers, and sandbox lifecycle management.
`app/cli/` implements development commands and workflow verification, invoked
with `python -m app.cli.commands`.

Vite builds `app/dashboard/dist/`; only those assets join the backend in the Python
package and final container. `/` redirects to `/dashboard/`, where HTML fallback supports
page refreshes and client-side navigation; missing assets return 404.

## Persistence and ownership

PostgreSQL is authoritative; executor threads and events are transient, not a
distributed queue. Queued work survives restart. A lifetime PostgreSQL advisory
lock permits one dispatcher per database; a second API refuses startup, and
ownership loss interrupts work.

Apply Alembic migrations before API startup; the API neither runs DDL nor checks
migration revisions. Follow [startup](getting-started.md) and
[schema-change instructions](../CONTRIBUTING.md#schema-changes).

## Execution and transactions

1. Admission validates ownership, target origin/path, plugins, and local image availability;
   commits `queued` with its audit event; then submits the assessment ID.
2. The worker locks the assessment, rechecks policy, and commits `running` with
   a durable attempt, resource names, and operation journal before Docker commands.
   Creation intent precedes each command; resource IDs are committed before
   container startup. Creation, startup, and cleanup removal are separate operations.
3. One Docker bundle or website session fetches the ordered routes using the shared
   HTTP observation contract. Every selected plugin receives an independent copy
   and the same immutable analysis context. After every selected plugin succeeds,
   a short transaction atomically records that route, normalized findings,
   evidence, and its audit event. Incomplete routes publish no findings.
4. Finalization locks the assessment and commits the execution outcome, verified
   cleanup, coverage, release verdict, comparison, and terminal audit event.
   Publication requires a terminal attempt and verified cleanup. Failed or
   cancelled batches may then expose labelled findings from completed routes.
   Finding payloads live only in normalized finding/evidence tables; route
   summaries derive their counts from those records.

Evidence has a required `finding_id`; assessment and project ownership derive
from that finding.

`app/assessments/policy.py` owns target boundary rules;
`app/assessments/lifecycle.py` owns transitions and finalization.
[Plugin manifests](plugins.md) produce the API catalog.

## Recovery

Startup and background reconciliation recover orphaned nonterminal attempts after
crashes, shutdown, or transient finalization failures, including while the API
remains running. Docker permits one retry (two attempts total), requiring verified
cleanup, valid target boundaries, and a locally available image. Cleanup itself
requires no target image, so removing an image cannot prevent resource removal. Persisted resource names and labels survive
crashes; journal ownership tokens fence stale workers. Websites fail interrupted
execution without replaying external requests; closure acknowledgement or verified
process exit proves HTTP cleanup.

Finalized cancellations and failures, including deadline, policy, and plugin
errors, are not retried. Later reconciliation can resolve a failed assessment's
pending cleanup without re-executing its plugins or turning the failure into a pass.
See [workflow configuration and coverage](workflows.md) for route plans and profiles.

A separate thread revisits failed cleanup and orphaned attempts after startup,
waiting 30 seconds between passes without blocking readiness or unrelated work.
Normal shutdown signals interruption and waits for workers and reconciliation.
Docker cleanup commands have individual timeouts; a blocking synchronous plugin
can delay interruption and total shutdown.

Journal writes use short row-locked transactions; Docker commands run outside
them. See the [cleanup guarantees](security-model.md#cleanup-and-failure) for
resource ownership, uncertain creation, and verification requirements.

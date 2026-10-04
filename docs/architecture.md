# Architecture

SEIRETH is one Python 3.14 FastAPI application with synchronous SQLAlchemy/Psycopg
and PostgreSQL 18. Its process-local dispatcher has two assessment worker threads,
plus separate ownership monitoring and cleanup reconciliation threads.

`app/main.py` assembles FastAPI, dispatcher lifespan, health, and built GUI
serving. `app/api/` groups resource routes and shared HTTP authorization;
`app/web/` contains the React/TypeScript frontend and its tests.
Native and Docker servers use `app.main:app`.

Vite builds `app/web/dist/`; only those assets join the backend in the Python
package and final container. `/` redirects to `/app/`, where HTML fallback supports
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

1. Admission validates ownership, target, scope, plugins, and image policy;
   commits `queued` with its audit event; then submits the assessment ID.
2. The worker locks the assessment, rechecks policy, and commits `running` with
   a durable attempt, resource names, and operation journal before Docker commands.
   Creation intent precedes each command; resource IDs are committed before
   container startup. Creation, startup, and cleanup removal are separate operations.
3. The immutable registry resolves plugins in request order. The orchestrator
   fetches once through the sandbox, which validates an observation containing the
   original authorized URL and ordered repeated headers. The orchestrator gives
   each plugin an independent deep copy and owns cleanup. Findings remain buffered
   until execution and cleanup succeed.
4. Finalization locks the assessment and atomically commits results, findings,
   evidence, attempt outcome, and terminal audit event.

Evidence has a required `finding_id`; assessment and project ownership derive
from that finding.

`app/policy.py` owns authorization rules; `app/lifecycle.py` owns transitions and
finalization. [Plugin manifests](plugins.md) produce the API catalog.

## Recovery

Startup and background reconciliation recover orphaned nonterminal attempts after
crashes, shutdown, or transient finalization failures, including while the API
remains running. One retry is allowed (two attempts total), requiring verified
cleanup and current authorization. Persisted resource names and labels survive
crashes; journal ownership tokens fence stale workers.

Finalized cancellations and failures, including deadline, policy, and plugin
errors, are not retried. Later reconciliation can resolve a failed assessment's
pending cleanup without re-executing its plugins.

A separate thread revisits failed cleanup and orphaned attempts after startup,
waiting 30 seconds between passes without blocking readiness or unrelated work.
Normal shutdown interrupts work and performs bounded cleanup.

Journal writes use short row-locked transactions; Docker commands run outside
them. See the [cleanup guarantees](security-model.md#cleanup-and-failure) for
resource ownership, uncertain creation, and verification requirements.

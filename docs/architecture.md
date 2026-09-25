# Architecture

SEIRETH is one Python 3.14 FastAPI application with synchronous SQLAlchemy/Psycopg,
PostgreSQL 18, and a two-thread process-local dispatcher. Redis, separate workers,
a frontend, and Go services are not dependencies.

## Persistence and ownership

PostgreSQL is authoritative; executor threads and events are transient, not a
distributed queue. Queued work survives restart. A lifetime PostgreSQL advisory
lock permits one dispatcher per database; a second API refuses startup, and
ownership loss interrupts work.

Alembic owns schema changes: `0001_initial_schema` is the baseline;
`0002_plugin_selection` adds selection and remediation. The API neither runs DDL
nor checks migration revisions. Follow [startup](getting-started.md) and
[schema-change instructions](../CONTRIBUTING.md#schema-changes).

## Execution and transactions

1. Admission validates ownership, target, scope, plugins, and image policy;
   commits `queued` with its audit event; then submits the assessment ID.
2. The worker locks the assessment, rechecks policy, and commits `running` with
   a durable attempt, resource names, and operation journal before Docker commands.
   Creation intent precedes each command; resource IDs are committed before
   container startup. Creation, startup, and cleanup removal are separate operations.
3. The immutable registry resolves plugins in request order. The orchestrator
   fetches headers once, passes each plugin an independent typed observation,
   and owns cleanup. Findings remain buffered until execution and cleanup succeed.
4. Finalization locks the assessment and atomically commits results, findings,
   evidence, attempt outcome, and terminal audit event.

`app/policy.py` owns authorization rules; `app/lifecycle.py` owns transitions and
finalization. [Plugin manifests](plugins.md) produce the API catalog.

## Recovery

Persisted names and assessment/attempt labels survive crashes. Startup reconciles
interrupted attempts before allowing one retry (two attempts total), requiring
verified cleanup and current authorization. Only crash/shutdown interruptions
qualify; cancellation, deadlines, policy rejection, and plugin errors do not.
Normal shutdown interrupts work and performs bounded cleanup.

A separate reconciliation thread revisits failed cleanup immediately after startup
and every 30 seconds without re-executing failed assessments or blocking readiness
or unrelated work. It also recovers orphaned nonterminal work.

Journal ownership tokens fence stale workers. Journal writes use short row-locked
transactions; Docker commands run outside them. See the
[cleanup guarantees](security-model.md#cleanup-and-failure) for resource ownership,
uncertain creation, and verification requirements.

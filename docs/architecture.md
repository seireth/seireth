# Architecture

SEIRETH is one Python 3.14 FastAPI application with PostgreSQL 18, synchronous
SQLAlchemy/Psycopg, and a two-thread process-local dispatcher. No Redis, separate
worker service, frontend, or Go service is required.

## Startup and persistence

Alembic revision files create and evolve the schema. Run `python -m app migrate`
explicitly for native startup. `python -m app docker-up` stops any existing API,
waits for PostgreSQL, runs migrations with `docker compose run --rm`, then starts
the API only on success. The API does not check migration revisions or run DDL. One PostgreSQL advisory lock guards the dispatcher for the application
lifetime; a second API process refuses to start. Ownership loss interrupts work.

## Execution

1. Admission validates project ownership, target, scope, profile, and image policy.
2. The API persists `queued` and its audit event, then submits the assessment ID.
3. The worker locks the assessment row, rechecks policy, creates a durable attempt
   with resource names, and commits `running` before issuing Docker commands.
4. The plugin receives an execution interface; orchestration owns cleanup.
5. Findings remain buffered until successful execution and verified cleanup.
6. Finalization locks the assessment and commits results, findings, evidence,
   attempt outcome, and terminal audit event together.

Policy rules live in `app/policy.py`; state transitions and finalization live in
`app/lifecycle.py`. The remaining API, database, worker, plugin, sandbox, and
verification modules keep their existing responsibilities.

## Recovery

Resource names and assessment/attempt ownership labels survive process failure.
Startup reconciles interrupted attempts before retrying once (two attempts total).
Only crash/shutdown interruptions qualify. Cancellation, deadline expiry, policy
rejection, and plugin errors are not retried automatically. Every retry requires
verified cleanup and current authorization. Failed cleanup remains recorded and
is revisited on later startup without re-executing the failed assessment.

The API is deliberately single-process. PostgreSQL stores authoritative state;
the thread pool and events are transient execution mechanisms, not a distributed
queue. Queued work survives restart. Normal shutdown interrupts active work and
performs bounded cleanup; a later startup may retry the interrupted attempt.

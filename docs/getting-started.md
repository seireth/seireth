# Getting started

Install Python 3.14 and Docker Desktop/Engine. Create and activate `.venv`, copy
`.env.example` to `.env`, then install the project:

```bash
python -m pip install -e ".[test,quality,security]"
docker compose up -d postgres
python -m app migrate
python -m app serve
```

Use `Copy-Item .env.example .env` in PowerShell or `cp .env.example .env` on Unix.
The API starts at http://127.0.0.1:8000. In a second activated terminal:

```bash
python -m app verify --expected-backend inmemory
```

The in-memory backend demonstrates the API lifecycle without assessing a real host.
PostgreSQL remains required for persistence.

## Development without Docker

Use a native PostgreSQL 18 installation with a database and login created for
Seireth. Set the connection URL and select the simulated backend, then run:

```powershell
$env:SEIRETH_DATABASE_URL='postgresql+psycopg://seireth:YOUR_PASSWORD@127.0.0.1:5432/seireth'
$env:SEIRETH_SANDBOX_BACKEND='inmemory'
python -m app migrate
python -m app serve
```

In a second terminal, `python -m app verify --expected-backend inmemory` exercises
the complete API workflow. Docker is not needed for this setup. The in-memory
backend simulates response headers; real isolated target assessments require
Docker. Database tests work with native PostgreSQL too: point
`SEIRETH_TEST_ADMIN_URL` at that server's admin connection.

## Real Docker assessment

Stop the local API to free port 8000 and release its dispatcher lock:

```bash
docker build -t seireth/demo-target:local examples/demo-target
docker pull python:3.14-slim
python -m app docker-up
python -m app verify --expected-backend docker --timeout-seconds 120
```

The startup command waits for PostgreSQL, runs migrations in a temporary container
that removes itself, then starts the API only on success and waits for HTTP 200
from its `/health` endpoint. Verification can run immediately after it returns.
API readiness has a 120-second limit after build and migration; override it with
`python -m app docker-up --timeout-seconds 180` (fractional seconds round up).
A failed startup returns a nonzero exit code and leaves containers for inspection
with `docker compose ps -a` and `docker compose logs api`. It stops an existing API
before migrating. Use this command instead of plain `docker compose up`, which
does not run migrations. Stop with
`docker compose down`; the PostgreSQL volume is retained. The owned demo target's
`/slow` path delays briefly for cancellation and crash-recovery integration tests.

## Schema changes

Revision files live under `app/migrations/versions`. To generate the next revision:

```bash
python -m alembic revision --autogenerate -m "describe schema change"
python -m app migrate
```

Review generated operations before applying them. Do not edit already deployed
revisions. Run migrations before starting the API directly; the API does not
check the schema revision or apply migrations. Request handlers do not modify the schema.

## Tests

Tests create a uniquely named PostgreSQL database and drop only that database.
Set a test-admin connection explicitly; it needs permission to create databases.
It must point at a local/disposable server, never a production server.

PowerShell:

```powershell
$env:SEIRETH_TEST_ADMIN_URL='postgresql+psycopg://seireth:seireth-local@127.0.0.1:5432/postgres'
python -m app test
$env:SEIRETH_DOCKER_TESTS='1'
python -m pytest tests/test_api_process.py
```

Unix:

```bash
export SEIRETH_TEST_ADMIN_URL='postgresql+psycopg://seireth:seireth-local@127.0.0.1:5432/postgres'
python -m app test
SEIRETH_DOCKER_TESTS=1 python -m pytest tests/test_api_process.py
```

Pure tests can run without PostgreSQL:
`python -m pytest tests/test_scope_urls.py tests/test_verify.py tests/test_docker_sandbox.py`.
The Docker tests require the built demo image and pulled runner image.

If PostgreSQL is unavailable, check `docker compose ps` and database logs. If a
second API refuses dispatcher ownership, stop the existing API process; do not
force-unlock a live dispatcher. Docker failures should be investigated using
assessment labels and API logs.

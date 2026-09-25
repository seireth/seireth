# Getting started

## Prerequisites and setup

Use Python 3.14 and PostgreSQL 18. Docker Desktop/Engine can host PostgreSQL and
is required for real assessments. Run commands from the repository root.

```powershell
# Windows PowerShell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

```bash
# macOS / Linux
python3.14 -m venv .venv
source .venv/bin/activate
cp .env.example .env
```

## Simulated assessment

The example selects `inmemory`: no host is assessed, but PostgreSQL remains required.

```bash
python -m pip install -e .
docker compose up -d --wait postgres
python -m app migrate
python -m app serve
```

For **native PostgreSQL without Docker**, create a Seireth database and login,
set `SEIRETH_DATABASE_URL` in `.env` to their `postgresql+psycopg://` connection URL,
and skip the Compose command. Keep `SEIRETH_SANDBOX_BACKEND=inmemory`.

The example API address is http://127.0.0.1:8000; open `/docs` for interactive
schemas. In a second activated terminal:

```bash
python -m app verify --expected-backend inmemory
```

[Verification](../app/verify.py) checks registration, authorization, execution,
findings, cleanup, and audit ordering. `--expected-backend` asserts the backend;
it does not select it. See [Assessments](assessments.md) for individual requests.

## Real Docker assessment

Stop the native API with Ctrl+C to free its port and dispatcher lock, then run:

```bash
docker build -t seireth/demo-target:local examples/demo-target
docker pull python:3.14-slim
python -m app docker-up
python -m app verify --expected-backend docker --timeout-seconds 120
```

`docker-up` builds, stops any Compose API, waits for PostgreSQL, runs a temporary
migration container with `--rm`, then starts the API only on success and waits for
HTTP 200 from `/health`. Plain `docker compose up` does not migrate.

Readiness defaults to 120 seconds after build/migration. Override with
`python -m app docker-up --api-ready-timeout-seconds 180`; fractional seconds round up.
See [Configuration](configuration.md) for overrides and migration timeouts.

Stop with `docker compose down`; the PostgreSQL volume is retained.

## Troubleshooting

- Startup failure returns nonzero and leaves containers for inspection:
  `docker compose ps -a` and `docker compose logs api`.
- PostgreSQL unavailable: check `docker compose ps` and `docker compose logs postgres`.
- Dispatcher ownership refused: stop the existing API; never force-unlock a live dispatcher.
- Sandbox failure: inspect assessment labels and logs using the
  [cleanup procedure](security-model.md#cleanup-and-failure).

For tests and schema changes, see [Contributing](../CONTRIBUTING.md).

# Configuration

Copy `.env.example` to `.env`. Native application settings use `SEIRETH_`, with
shell environment variables taking precedence over `.env`. Compose handles
overrides separately, as described below. Never commit local credentials. The
example password is for loopback development: change it and the connection URL
together, using URL-safe credentials without unescaped URL delimiters.

## Required settings

| Setting | Meaning |
| --- | --- |
| `SEIRETH_API_HOST`, `SEIRETH_API_PORT` | Native binding / Docker published address; port 1â€“65535; example `127.0.0.1`, `8000` |
| `SEIRETH_DATABASE_URL` | `postgresql+psycopg://...`; SQLite unsupported |

## Optional defaults

| Setting | Default / meaning |
| --- | --- |
| `SEIRETH_ASSESSMENT_TIMEOUT_SECONDS` | 60; positive finite execution timeout |
| `SEIRETH_BUNDLE_RUNNER_IMAGE` | `seireth/runner:local`; shared HTTP runner for Docker bundles |
| `SEIRETH_OPERATOR_CONFIG_FILE` | empty; optional operator-owned JSON profiles and secret references |
| `SEIRETH_CLEANUP_TIMEOUT_SECONDS` | 60; independent foreground cleanup budget for bundles |
| `SEIRETH_DOCKER_MEMORY`, `SEIRETH_DOCKER_CPUS`, `SEIRETH_DOCKER_PIDS_LIMIT` | `256m`, `0.5`, `64`; CPUs must be positive and finite, PIDs a positive integer |
| `SEIRETH_DOCKER_TIMEOUT_SECONDS` | 15; positive finite base command timeout |

Target registration requires a base URL and source kind. Docker targets require
an image; website targets reject images and use the existing deployment.
Docker registration and submission require local images; submission freezes their
IDs for execution and retries.
`GET /api/v1/target-images` discovers tagged images; callers may supply another
local reference directly. Build or pull images explicitly; both target and runner
containers use `--pull=never`. Websites need no Docker daemon. Cleanup remains
possible when an image is unavailable.

## Timeouts

Single-URL submissions retain the configured assessment timeout. Route plans
default to the startup budget plus each route's request budget and five seconds
for analysis, capped at 900 seconds. Requests default to 10 seconds and are bounded
by the overall deadline. Synchronous analyzers are checked between calls and
cannot be forcibly preempted. Cleanup has a separate 60-second foreground budget;
unresolved resources remain pending for reconciliation.

See [workflows](workflows.md) for public/private website grants, custom CAs,
runtime authentication, launch profiles, and supplied-session requirements.

## Compose overrides

Compose requires `POSTGRES_PASSWORD`, also reflected in the native connection URL.
It overrides the API database URL with its bundled `postgres:5432` connection.
Compose loads API settings from `.env` through `env_file`. Shell variables override
values used in Compose interpolation, such as the published API host/port and
database password. They are not automatically forwarded into the API container:
put optional settings such as `SEIRETH_DOCKER_CPUS` in `.env`, or explicitly add
them to the service's `environment` in `docker-compose.yml`.

The API publishes the configured host/port; its listener and health probe stay on
8000. Verification maps `0.0.0.0` / `::` to loopback destinations. PostgreSQL is
published on `127.0.0.1:5432`, with its named volume at `/var/lib/postgresql`.
The API and temporary migration job share one application image.

`docker-up --api-ready-timeout-seconds` excludes build/migration time. Runtime
database connection and statement timeouts are five seconds. Migrations have
separate connection (5s), lock (30s), and statement (300s) limits.

Tests require an explicit `SEIRETH_TEST_ADMIN_URL` for disposable databases;
see [Contributing](../CONTRIBUTING.md#tests).

## GUI development

| Setting | Default / meaning |
| --- | --- |
| `SEIRETH_UI_API_URL` | `http://127.0.0.1:8000`; API address for Vite's development proxy |
| `SEIRETH_UI_URL` | `http://127.0.0.1:8000`; deployment address for Playwright tests |
| `SEIRETH_DOCKER_EXECUTABLE` | Absolute Docker CLI path for Playwright cleanup checks; defaults to `/usr/bin/docker` or `C:\Program Files\Docker\Docker\resources\bin\docker.exe` on Windows |


## Reset to the current schema

Apply baseline `0001_current_schema` to an empty database; do not stamp an
existing incompatible database. To reset disposable Compose data:

1. Stop the API gracefully and [verify owned-resource cleanup](security-model.md#cleanup-and-failure)
   before discarding its journal. Resolve pending cleanup first.
2. Run `docker compose down --volumes` from this repository. This deletes the
   deployment's PostgreSQL data.
3. Run `python -m app.cli.commands docker-up` to recreate the database, migrate, and start.

For native startup, recreate only the configured disposable database, run
`python -m app.cli.commands migrate`, then start the API. Tests use separate databases.

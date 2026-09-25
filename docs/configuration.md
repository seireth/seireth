# Configuration

Copy `.env.example` to `.env`; environment variables override it. Application
settings use `SEIRETH_`. Never commit local credentials. The example password is
for loopback development: change it and the connection URL together, using
URL-safe credentials without unescaped URL delimiters.

## Required settings

| Setting | Meaning |
| --- | --- |
| `SEIRETH_API_HOST`, `SEIRETH_API_PORT` | Native binding / Docker published address; port 1–65535; example `127.0.0.1`, `8000` |
| `SEIRETH_DATABASE_URL` | `postgresql+psycopg://...`; SQLite unsupported |
| `SEIRETH_SANDBOX_BACKEND` | `inmemory` or `docker`; example selects `inmemory` |
| `SEIRETH_DOCKER_TARGET_IMAGE` | Default target image |
| `SEIRETH_DOCKER_ALLOWED_TARGET_IMAGES` | JSON array of exact allowed image references |

## Optional defaults

| Setting | Default / meaning |
| --- | --- |
| `SEIRETH_ASSESSMENT_TIMEOUT_SECONDS` | 60; positive finite execution timeout |
| `SEIRETH_DOCKER_RUNNER_IMAGE` | `python:3.14-slim`; operator-controlled |
| `SEIRETH_DOCKER_MEMORY`, `SEIRETH_DOCKER_CPUS`, `SEIRETH_DOCKER_PIDS_LIMIT` | `256m`, `0.5`, `64` |
| `SEIRETH_DOCKER_TIMEOUT_SECONDS` | 15; positive finite command timeout |

Registration and every execution/retry enforce the image allowlist, including
simulated registration. Removing an image blocks future execution, not active
runs. Prefer immutable digests; allowlisting does not establish safety.

The execution deadline is the earlier of timeout and scope expiry. Cleanup uses
separate bounded Docker command timeouts and can continue after expiry.

## Compose overrides

Compose requires `POSTGRES_PASSWORD`, also reflected in the native connection URL.
It overrides the API database URL with its bundled `postgres:5432` connection and
selects `docker`. The runner uses its configured image or the application default.

The API publishes the configured host/port; its listener and health probe stay on
8000. Verification maps `0.0.0.0` / `::` to loopback destinations. PostgreSQL is
published on `127.0.0.1:5432`, with its named volume at `/var/lib/postgresql`.
The API and temporary migration job share one application image.

`docker-up --api-ready-timeout-seconds` excludes build/migration time. Migrations
have separate connection (5s), lock (30s), and statement (300s) limits; normal API
query limits are unchanged.

Tests require an explicit `SEIRETH_TEST_ADMIN_URL` for disposable databases;
see [Contributing](../CONTRIBUTING.md#tests).

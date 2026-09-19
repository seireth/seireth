# Configuration

Copy `.env.example` to `.env`. Application settings use the `SEIRETH_` prefix;
environment variables override the local file. Compose also reads `POSTGRES_PASSWORD`.
Do not commit local credentials. The example password is for loopback development.
Change it and the connection URL together, using URL-safe credentials.

| Setting | Purpose/default |
| --- | --- |
| `SEIRETH_API_HOST`, `SEIRETH_API_PORT` | Required native binding and Docker published address; port 1-65535; example `127.0.0.1`, `8000` |
| `SEIRETH_DATABASE_URL` | Required `postgresql+psycopg://...` URL; SQLite is unsupported |
| `SEIRETH_SANDBOX_BACKEND` | Required `inmemory` or `docker` |
| `SEIRETH_ASSESSMENT_TIMEOUT_SECONDS` | Positive finite execution deadline; default 60 seconds |
| `SEIRETH_DOCKER_TARGET_IMAGE` | Required default target image |
| `SEIRETH_DOCKER_ALLOWED_TARGET_IMAGES` | Required JSON array of exact allowed image references |
| `SEIRETH_DOCKER_RUNNER_IMAGE` | Operator-controlled runner; default `python:3.14-slim` |
| `SEIRETH_DOCKER_MEMORY`, `SEIRETH_DOCKER_CPUS`, `SEIRETH_DOCKER_PIDS_LIMIT` | Default `256m`, `0.5`, `64` |
| `SEIRETH_DOCKER_TIMEOUT_SECONDS` | Positive finite command timeout; default 15 seconds |
| `POSTGRES_PASSWORD` | Compose database password, also reflected in local connection URL |
| `SEIRETH_TEST_ADMIN_URL` | Explicit PostgreSQL admin connection for disposable test databases |

Target registration and every execution/retry enforce the image allowlist. Removing
an image prevents future execution; it does not terminate an already executing run.
Prefer immutable digests for reproducible image identity. Listing an image does not
prove it is safe. The in-memory backend also checks target registration policy.

The execution deadline is the earlier of the configured timeout and scope expiry.
Cleanup has separate bounded Docker command timeouts, so it can run after expiry.

Compose deliberately selects the Docker backend and its bundled database at
`postgres:5432`, overriding the native connection URL and backend. The published
API address uses `SEIRETH_API_HOST` and `SEIRETH_API_PORT`; its internal listener
and health probe stay on port 8000. PostgreSQL stays published on loopback port
5432. The runner image uses the configured value or the application default.
Verification maps wildcard bindings (`0.0.0.0`/`::`) to loopback destinations. PostgreSQL
18 uses the named volume at `/var/lib/postgresql`. Database credentials should not
contain unescaped URL delimiters when interpolated into the Compose URL.

The API and temporary migration job share one application image.
`docker-up --api-ready-timeout-seconds` limits only API readiness; it does not
limit the build or migration duration. Migrations use separate connection (5s),
lock (30s), and statement (300s) limits. These do not change normal API query limits.

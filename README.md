# Seireth

Seireth runs authorized, bounded security assessments in isolated
environments. MVP-0 supports passive HTTP security-header checks.

## Requirements

- Python 3.14
- Docker Desktop for Docker-backed assessments

## Local setup

Create a virtual environment, install the project, and create the local
configuration file:

```bash
python -m venv .venv
python -m pip install -e ".[test]"
copy .env.example .env       # Windows
cp .env.example .env         # macOS/Linux
```

Run the API:

```bash
python -m app serve
```

Run the tests:

```bash
python -m app test
```

Run the end-to-end verification workflow:

```bash
python -m app verify
```

The API listens at `http://127.0.0.1:8000`.

- OpenAPI UI: `http://127.0.0.1:8000/docs`
- OpenAPI schema: `http://127.0.0.1:8000/openapi.json`
- Health check: `http://127.0.0.1:8000/health`

## Configuration

Copy `.env.example` to `.env`. The application reads `SEIRETH_` variables from
`.env`; `.env` is not committed.

Required project settings:

```env
SEIRETH_API_HOST=127.0.0.1
SEIRETH_API_PORT=8000
SEIRETH_ENVIRONMENT=local
SEIRETH_SANDBOX_BACKEND=inmemory
SEIRETH_DOCKER_TARGET_IMAGE=seireth/demo-target:local
SEIRETH_DOCKER_ALLOWED_TARGET_IMAGES=["seireth/demo-target:local"]
```

`SEIRETH_DOCKER_ALLOWED_TARGET_IMAGES` is the server-side allowlist for target
images. A target can use only an image listed there. Use immutable image
digests for deployed environments.

## Docker assessments

Build the example target:

```bash
docker build -t seireth/demo-target:local ./examples/demo-target
```

Start the API with Docker Compose:

```bash
docker compose up --build
```

Compose requires a project `.env` file and loads it into the API container.
The Compose service uses the Docker sandbox, stores the SQLite database in a
volume, and exposes the API on port `8000`.

Docker-backed assessments create and remove:

1. A private assessment network.
2. A restricted target container.
3. A short-lived assessment runner.

The API container needs access to the Docker socket for this mode.

## Assessment workflow

1. Create a project.
2. Register an allowlisted target.
3. Create a time-bounded authorization scope.
4. Queue a passive assessment.
5. Poll the assessment or results endpoint.
6. Review findings and audit events.

Assessment creation returns `202 Accepted`. The initial status is normally
`queued` and its `result` is `null`. Poll until the status is `completed`,
`failed`, or `cancelled`.

Completed results currently contain:

```json
{
  "plugin": "security-headers",
  "finding_count": 3,
  "sandbox_backend": "inmemory",
  "cleanup_verified": true,
  "completed_at": "2026-09-14T12:00:00+00:00"
}
```

## Current scope

- One passive security-header plugin.
- One local-development actor.
- Process-local assessment worker.
- In-memory and Docker sandbox backends.
- Origin-, path-, and time-bounded authorization scopes.
- Server-controlled Docker image allowlist.
- Restricted Docker assessment resources with cleanup verification.

MVP-0 is not a general internet scanner or a multi-user production service.
Only assess systems for which you have explicit authorization.

## Project documentation

- [Architecture](.docs/03-architecture.md)
- [Plugins and tests](.docs/04-plugins-and-tests.md)
- [Sandbox and security](.docs/05-sandbox-and-security.md)
- [Roadmap and MVP](.docs/10-roadmap-and-mvp.md)
- [Contributing](CONTRIBUTING.md)
- [Security reporting](SECURITY.md)

# Seireth

> Authorized, reproducible security validation in isolated environments.

Seireth is an early MVP for running bounded security checks against targets
that the operator owns or is explicitly authorized to test. MVP-0 currently
supports one passive check: HTTP security headers.

## Quick start

The commands work on Windows, macOS, and Linux:

```bash
python -m venv .venv
python -m pip install -e ".[test]"
python -m app serve
python -m app verify
```

Run the tests with:

```bash
python -m app test
```

The API is available at `http://127.0.0.1:8000`. FastAPI generates the
interactive OpenAPI documentation automatically at
`http://127.0.0.1:8000/docs`; the raw schema is available at
`http://127.0.0.1:8000/openapi.json`.

## Configuration

Settings are defined, typed, and given safe defaults in `app/config.py`.
Pydantic loads variables with the `SEIRETH_` prefix from an uncommitted `.env`
file when the Python process runs locally. The example contains only security
and deployment decisions; ordinary values such as ports, database path,
runner image, resource limits, and timeouts use the defaults in
`app/config.py`. Create the local override file from the example:

```bash
copy .env.example .env       # Windows
cp .env.example .env         # macOS/Linux
```

`.env.example` is only a template; it is not read directly and must not contain
secrets. In deployed environments, provide the same variables through the
deployment platform or a secret manager. Authentication is local-development
only by default and fails closed outside local mode unless `SEIRETH_API_KEY`
is configured.

The Docker image allowlist is server-controlled:

```env
SEIRETH_DOCKER_ALLOWED_TARGET_IMAGES=["acme/test-app@sha256:..."]
```

Target requests may select only an image in this list. Prefer immutable image
digests over mutable tags such as `latest`.

When using Docker Compose, the container receives the variables declared in
`docker-compose.yml`; a host `.env` file is not automatically copied into the
container. Add deployment values to Compose or provide them through the
deployment environment rather than mounting a developer `.env` file.

## Docker-backed assessments

The default backend is deterministic `inmemory`, so local tests make no
network requests. To use the Docker backend:

```bash
docker build -t seireth/demo-target:local ./examples/demo-target
docker compose up --build
python -m app verify
```

Docker mode creates, per assessment:

1. A private internal network.
2. A restricted target container from the registered allowlisted image.
3. A short-lived Python runner that requests the target and captures response
   headers.
4. A cleanup operation that removes the runner, target, and network.

The Compose API container is `seireth-api-01`. Assessment resources are
created dynamically and remain separate Docker resources:

```text
seireth-target-<target-name>-<assessment-id>
seireth-assessment-runner-<assessment-id>
seireth-assessment-<unique-id>    # network
```

The API requires access to the Docker socket to create these resources. Use
this mode only on trusted infrastructure; do not expose the Compose setup to
untrusted users.

## API workflow

```text
Create project
  → register trusted target
  → create time-bounded URL scope
  → queue passive assessment
  → poll assessment status/results
  → review findings and audit events
```

Assessment creation returns `202 Accepted` with a `Location` header. The
initial response normally has `status: "queued"` and `result: null`; fetch the
assessment or `/results` endpoint until it reaches `completed`, `failed`, or
`cancelled`.

The current completed result is intentionally small and stable:

```json
{
  "plugin": "security-headers",
  "finding_count": 3,
  "sandbox_backend": "inmemory",
  "cleanup_verified": true,
  "completed_at": "2026-09-14T12:00:00+00:00"
}
```

The plugin name and result fields are MVP-0 application contracts, not
environment settings. They should become versioned result schemas as more
profiles and plugins are added.

## Security boundaries and limitations

- Assess only systems for which written authorization and a clear scope exist.
- Scope validation binds each assessment to the registered target origin/path
  and expiry time.
- Project resources are restricted to their authenticated owner.
- Docker target images are allowlisted by server configuration.
- Assessments run with read-only filesystems, dropped capabilities, resource
  limits, and private networks.
- Cleanup failures are reported as assessment failures.

MVP-0 is not a general internet scanner or a production-ready multi-tenant
platform. The worker dispatcher is currently process-local, authentication is
a single bearer key rather than a full identity provider, and Docker socket
access is a high-privilege trusted-host boundary.

## Documentation

The design documents are in [`.docs/`](.docs/), including:

- [Architecture](.docs/03-architecture.md)
- [Plugins and tests](.docs/04-plugins-and-tests.md)
- [Sandbox and security](.docs/05-sandbox-and-security.md)
- [Roadmap and MVP](.docs/10-roadmap-and-mvp.md)

See [`CONTRIBUTING.md`](CONTRIBUTING.md) before making changes and
[`SECURITY.md`](SECURITY.md) for vulnerability reporting.

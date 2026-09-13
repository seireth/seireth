# Seireth

> Authorized, reproducible security validation in isolated, disposable environments.

Seireth is an open-source platform for performing authorized security assessments against software products and applications in controlled environments. It is intended to help software, security, and DevSecOps teams run repeatable checks, collect evidence, track findings, verify remediation, and produce reports.

## Status

Seireth now includes a minimal MVP-0 vertical slice in `app/`.

## Run MVP-0

The commands below are the same on Windows, macOS, and Linux. They do not
require activating the virtual environment:

```bash
python -m venv .venv
python -m pip install -e ".[test]"
python -m app serve
python -m app verify
python -m app test
```

Runtime settings use the `SEIRETH_` environment-variable prefix and are loaded
from an uncommitted `.env` file when present. Copy `.env.example` to `.env` for
local configuration. Explicit CLI options override the corresponding settings.
For production, inject environment variables through the deployment platform
or a secret manager instead of committing `.env`.

`python -m app verify` runs the complete reachable API workflow against the
running server and prints the created resources, findings, JSON result, and
audit trail. Run it after `python -m app serve`. The OpenAPI UI is also
available at `/docs`, and results can be retrieved at
`/api/v1/assessments/{id}/results`.

Docker Compose starts the API and configures the Docker sandbox backend. Build
the deliberately vulnerable local demo image separately before running a
Docker-backed verification. The API image uses the Docker CLI and
the host Docker socket to create a per-assessment internal network; this is a
privileged deployment decision for trusted development hosts. Assessments are
restricted to `owned_demo` targets. Outside Compose, the default is the
deterministic in-memory backend, so tests never access remote targets. Set
`SEIRETH_SANDBOX_BACKEND=docker` and provide a local Docker CLI and daemon to
enable it. The runner image (`SEIRETH_DOCKER_RUNNER_IMAGE`, default
`python:3.12-slim`) must be available or pullable by Docker. The project audit
trail is available at
`/api/v1/projects/{id}/audit-events`.

For a Docker-backed run, use a second terminal for the API workflow:

```bash
docker build -t seireth/demo-target:local ./examples/demo-target
docker compose up --build
python -m app verify
```

The target image is not run as a Compose service. The Docker-backed assessment
starts a fresh target container and a short-lived
runner container on a private internal network for each assessment, then
removes both the target and network during cleanup. The API container requires
access to the Docker socket to perform this orchestration; do not expose this
Compose configuration to untrusted users or production hosts.

The `serve` and `test` commands invoke Uvicorn and Pytest through the same
Python interpreter used to install the project. To pass options through, use
`python -m app test -k scope` or `python -m app serve --port 8080`.

The virtual environment is ignored by Git. If `python` points to a system
installation on your machine, use that installation to create and install the
environment; the Seireth commands remain unchanged.

## Core workflow

```text
Register an authorized target
        ↓
Define scope and restrictions
        ↓
Create a disposable test environment
        ↓
Run selected security tests
        ↓
Verify and classify findings
        ↓
Collect evidence and reports
        ↓
Destroy the environment
        ↓
Verify cleanup
        ↓
Retest after remediation
```

## Principles

- **Authorized use only:** assessments must have explicit permission and an identifiable scope.
- **Isolation by default:** assessments should run in disposable environments with restricted resources and networking.
- **Deny by default:** missing, invalid, or ambiguous authorization must prevent execution.
- **Safe validation:** tests should use the minimum interaction and evidence needed to support a finding.
- **Reproducibility:** runs should identify the target, version, test profile, configuration, and environment.
- **Automatic cleanup:** environments must be cleaned up after success, failure, timeout, or cancellation.
- **Transparent limitations:** automated testing and container isolation do not guarantee that a target is secure or compliant.

Seireth is not an unrestricted internet scanner, a general-purpose exploitation framework, or a replacement for professional security testing.

## Documentation

The current specification is in [`.docs/`](.docs/):

- [Project overview](.docs/01-overview.md)
- [Targets and assessment lifecycle](.docs/02-targets-and-lifecycle.md)
- [Architecture and platform design](.docs/03-architecture.md)
- [Plugins and tests](.docs/04-plugins-and-tests.md)
- [Sandbox and security](.docs/05-sandbox-and-security.md)
- [Evidence, findings, and remediation](.docs/06-evidence-findings-and-remediation.md)
- [CRA and standards](.docs/07-cra-and-standards.md)
- [Reporting and interfaces](.docs/08-reporting-and-interfaces.md)
- [Technology stack](.docs/09-technology-stack.md)
- [Roadmap and MVP](.docs/10-roadmap-and-mvp.md)

## Planned technology

The initial design uses FastAPI and Python for orchestration and test modules, Go for sandbox lifecycle management, Next.js and TypeScript for the web interface, PostgreSQL for authoritative data, Redis and Dramatiq for transient job coordination, and Docker for the initial sandbox backend.

## Authorized use

Only assess systems, applications, repositories, images, and environments that you own or are explicitly authorized to test. Do not use Seireth against third-party or production targets without written permission and a clearly defined scope. See [`SECURITY.md`](SECURITY.md) for the security and disclosure policy.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) before proposing changes.

## License

Seireth is licensed under the [Apache License 2.0](LICENSE).
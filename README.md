<p align="center">
  <img src="docs/assets/seireth-logo.png" alt="SEIRETH" width="240">
</p>

<h1 align="center">SEIRETH</h1>

<p align="center">Authorized security checks. Disposable environments. Verified cleanup.</p>

<p align="center">
  <a href="https://github.com/seireth/seireth/actions/workflows/ci.yml"><img src="https://github.com/seireth/seireth/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/seireth/seireth/actions/workflows/security.yml"><img src="https://github.com/seireth/seireth/actions/workflows/security.yml/badge.svg" alt="Dependency security"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white" alt="Python 3.14"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue" alt="Apache License 2.0"></a>
</p>

SEIRETH runs bounded security assessments against authorized containerized
targets, records findings and audit events, and destroys the assessment
environment afterward.

**MVP-0:** a working local API with one passive HTTP security-header plugin.
It uses PostgreSQL 18, versioned Alembic migrations, and a process-local worker. It is not a multi-user production
service or a general internet scanner.

## How it works

```mermaid
flowchart LR
    A[Register & authorize] --> B[Queue assessment]
    B --> C[Run sandbox checks]
    C --> D[Destroy & verify cleanup]
    D --> E[Record outcome]
```

- **Bounded requests:** project, target, origin, path, and expiry checks.
- **Operator-controlled images:** requests select only allowlisted target images.
- **Disposable Docker resources:** a private network, restricted target, and runner.
- **Queryable outcomes:** JSON findings, cleanup status, and an audit trail.

## Getting started

Follow [the setup guide](docs/getting-started.md) for Python 3.14, PostgreSQL,
and native or Docker startup. The default in-memory backend simulates responses;
real assessments require Docker and access to its privileged socket.

After setup, `python -m app verify` exercises project registration, authorization,
assessment execution, results, cleanup, and audit ordering. See [Assessments](docs/assessments.md)
for API states and cancellation, and [Contributing](CONTRIBUTING.md) for development checks.

## Documentation

| Guide | What it covers |
| --- | --- |
| [Getting started](docs/getting-started.md) | Setup, verification, and troubleshooting |
| [Architecture](docs/architecture.md) | Current components and data flow |
| [Configuration](docs/configuration.md) | Settings, defaults, and image policy |
| [Assessments](docs/assessments.md) | Requests, polling, cancellation, and results |
| [Security model](docs/security-model.md) | Isolation boundaries and limitations |
| [Roadmap](docs/roadmap.md) | Implemented capabilities and future work |

Use only targets you are authorized to assess. Report SEIRETH vulnerabilities
through the process in [SECURITY.md](SECURITY.md).

Licensed under [Apache 2.0](LICENSE). The logo is reused from the
[SEIRETH GitHub organization](https://github.com/seireth).

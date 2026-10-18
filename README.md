<p align="center">
  <img src="docs/assets/seireth-logo.png" alt="SEIRETH" width="240">
</p>

<h1 align="center">SEIRETH</h1>

<p align="center">Authorized security checks. Disposable environments. Verified cleanup.</p>

<p align="center">
  <a href="https://github.com/seireth/seireth/actions/workflows/ci.yml"><img src="https://github.com/seireth/seireth/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI checks"></a>
  <a href="https://github.com/seireth/seireth/actions/workflows/build.yml"><img src="https://github.com/seireth/seireth/actions/workflows/build.yml/badge.svg?branch=main" alt="Tests, coverage and SonarQube"></a>
  <a href="https://github.com/seireth/seireth/actions/workflows/integration.yml"><img src="https://github.com/seireth/seireth/actions/workflows/integration.yml/badge.svg?branch=main" alt="Docker and browser integration"></a>
  <a href="https://sonarcloud.io/summary/new_code?id=seireth_seireth"><img src="https://sonarcloud.io/api/project_badges/measure?project=seireth_seireth&amp;metric=alert_status" alt="SonarQube quality gate"></a>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.14-3776AB?logo=python&amp;logoColor=white" alt="Python 3.14"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-blue" alt="Apache License 2.0"></a>
</p>

SEIRETH is a local, single-operator GUI and API for passive HTTP header and cookie
security checks. Assess an existing website or a disposable Docker application
with declared companion services. Route plans record response expectations,
coverage, evidence, and a strict release verdict in PostgreSQL 18.
SEIRETH verifies cleanup after execution.
Finished assessments can be downloaded as versioned JSON or self-contained HTML
with findings, remediation, validated evidence, and cleanup status.

## How it works

```mermaid
flowchart LR
    A[Register Docker or website target] --> B[Freeze route plan]
    B --> C[Fetch and analyze responses]
    C --> D[Close or destroy resources and verify cleanup]
    D --> E[Persist report and release verdict]
```

Targets bound requests by project, origin, and path. Choose routes and plugins;
runtime references supply authentication. Docker bundles use an internal network,
owned volumes, and pinned local images. Website connections validate and pin
destination addresses while preserving Host and TLS identity.
See [Docker and website workflows](docs/workflows.md) for reproducible examples.

## Checks

| Workflow                                                                            | Checks                                                                                      |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| [CI](https://github.com/seireth/seireth/actions/workflows/ci.yml)                   | Repository checks, Python quality, Frontend quality, Dependency review (pull requests only) |
| [Build](https://github.com/seireth/seireth/actions/workflows/build.yml)             | Tests, coverage and SonarQube                                                               |
| [Integration](https://github.com/seireth/seireth/actions/workflows/integration.yml) | Docker assessment lifecycle, including browser and packaged-asset checks                    |

## Getting started

Follow [Getting started](docs/getting-started.md) for setup and startup commands.
Website checks run natively; Docker checks require prepared images and access to
the Docker socket. Both workflows request real target responses.
Open `/dashboard/`
on the API address to use the GUI.

## Documentation

| Guide                                      | Purpose                                            |
| ------------------------------------------ | -------------------------------------------------- |
| [Getting started](docs/getting-started.md) | Run, verify, stop, and troubleshoot                |
| [Configuration](docs/configuration.md)     | Required settings, defaults, and Compose overrides |
| [Assessments](docs/assessments.md)         | Submit requests and interpret results              |
| [Docker and website workflows](docs/workflows.md) | Configure staging, service bundles, route coverage, and release gates |
| [Architecture](docs/architecture.md)       | Understand execution, persistence, and recovery    |
| [Plugin development](docs/plugins.md)      | Add approved checks                                |
| [Security model](docs/security-model.md)   | Understand boundaries and investigate cleanup      |
| [Roadmap](docs/roadmap.md)                 | Future priorities and directions                   |
| [Contributing](CONTRIBUTING.md)            | Develop, test, and change schemas                  |

Use only authorized targets. Report vulnerabilities through [SECURITY.md](SECURITY.md).
Licensed under [Apache 2.0](LICENSE).

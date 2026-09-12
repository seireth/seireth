# Seireth

> Authorized, reproducible security validation in isolated, disposable environments.

Seireth is an open-source platform for performing authorized security assessments against software products and applications in controlled environments. It is intended to help software, security, and DevSecOps teams run repeatable checks, collect evidence, track findings, verify remediation, and produce reports.

## Status

Seireth is currently in the **design and specification phase**. The repository currently contains the platform overview, architecture, security requirements, technology choices, and MVP roadmap. Implementation will be added incrementally.

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
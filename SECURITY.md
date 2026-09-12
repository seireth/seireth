# Security Policy

## Authorized use

Seireth is intended for authorized security validation in isolated environments. Use it only against targets for which you have explicit permission and a defined scope. You are responsible for isolation, credentials, network restrictions, resource limits, and cleanup. Seireth's results are not a guarantee that a target is secure or compliant.

## Reporting a vulnerability in Seireth

Do not disclose vulnerabilities in public issues. Submit them privately through GitHub's [Report a vulnerability](https://github.com/seireth/seireth/security/advisories/new) feature.

Include:

- Affected component, version, commit, or configuration
- Impact and security implications
- Reproduction steps or a minimal proof of concept
- Required permissions and environmental conditions
- Suggested mitigation, if known

Use redacted or synthetic examples. Do not include real secrets, personal data, or unauthorized target information.

## Disclosure process

Maintainers will validate the report, assess its impact, and coordinate remediation and disclosure with the reporter. Do not publicly disclose a vulnerability until a fix or mitigation is available and disclosure has been agreed.

## Security-sensitive areas

Security-sensitive changes include:

- Authorization and target-scope validation
- Sandbox creation, isolation, networking, and cleanup
- Credential and secret handling
- Host or container runtime access
- Project and tenant isolation
- Evidence, reports, and audit-log integrity
- Dependency, image, and plugin execution

Changes in these areas must include failure-path tests and fail closed when a security prerequisite cannot be verified.

## Supported versions

The project is currently in the design and specification phase. No production release support policy has been established yet. Supported versions will be listed here when releases begin.
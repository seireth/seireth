# Security Policy

## Authorized use

Seireth is security-sensitive software. It is designed for authorized security validation in isolated environments.

You must only use Seireth against targets for which you have explicit permission. Do not use it to scan, exploit, disrupt, or access third-party systems, public services, or production environments without written authorization and a defined scope. The project does not authorize activity against any target merely because the target is reachable.

Users are responsible for configuring appropriate isolation, credentials, network restrictions, resource limits, and cleanup verification before running assessments. Automated results are not a guarantee that a target is secure or compliant.

## Reporting a vulnerability in Seireth

Please do not report security vulnerabilities through public GitHub issues.

Until a dedicated private reporting address is published, report vulnerabilities privately through GitHub's **Report a vulnerability** feature for this repository, if available. Include:

- A clear description of the vulnerability and its impact
- The affected component, version, commit, or configuration
- Reproduction steps or a minimal proof of concept
- Any required permissions, assumptions, or environmental conditions
- Suggested mitigation, if known
- Whether the issue may expose credentials, target data, or other sensitive information

Please avoid including real secrets, personal data, or unauthorized target information. Use redacted or synthetic examples wherever possible.

## Disclosure process

The maintainers will acknowledge a report when practical, investigate its impact, and coordinate a fix and disclosure timeline with the reporter. Reports may be prioritized based on exploitability, affected scope, and impact on assessment isolation, authorization, evidence, or host security.

Do not publicly disclose the vulnerability until a fix or mitigation is available and a coordinated disclosure date has been agreed.

## Security-sensitive areas

Particular care is required for changes involving:

- Authorization and target-scope validation
- Sandbox creation, isolation, networking, and cleanup
- Credential and secret handling
- Host or container runtime access
- Project and tenant isolation
- Evidence, reports, and audit-log integrity
- Dependency, image, and plugin execution

Changes in these areas should include tests for failure paths and should fail closed when a security prerequisite cannot be verified.

## Supported versions

The project is currently in the design and specification phase. No production release support policy has been established yet. Supported versions will be listed here when releases begin.
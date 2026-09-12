# Contributing to Seireth

Thank you for helping improve Seireth.

## Before contributing

Read the project overview and architecture documents in [`.docs/`](.docs/), especially the requirements for authorization, isolation, cleanup, evidence, and auditability. Contributions must preserve the principle that assessments are authorized, scoped, and isolated.

## Proposing changes

For a substantial change, open an issue first to describe the problem, proposed approach, security implications, and affected components. Small documentation fixes may be submitted directly.

Keep changes focused. Update related documentation when behavior, interfaces, security requirements, or the roadmap changes.

## Security-sensitive changes

Do not include real credentials, private target information, production data, or undisclosed vulnerabilities in issues, commits, tests, or pull requests. Use synthetic targets and test data.

Changes affecting authorization, sandboxing, network restrictions, cleanup, secrets, authentication, project isolation, evidence, or audit events should include failure-path tests and explain how the security boundary is preserved. Report vulnerabilities privately as described in [`SECURITY.md`](SECURITY.md), rather than opening a public issue.

## Development expectations

As implementation is added:

- Use the repository's configured formatter, linter, type checker, and test commands.
- Add or update tests for behavior changes.
- Keep error handling explicit; do not silently ignore failed authorization, cleanup, or audit operations.
- Do not weaken secure defaults to make a test or local setup pass.
- Keep generated files, local databases, credentials, and build output out of commits.

## Pull requests

Pull requests should explain:

- What changed and why
- How the change was tested
- Any security, compatibility, migration, or operational impact
- Any documentation or follow-up work that remains

By contributing, you agree that your contributions are provided under the repository's Apache License 2.0.
# Contributing to Seireth

Thank you for helping improve Seireth.

Please read the [Code of Conduct](CODE_OF_CONDUCT.md) before participating.

## Before contributing

Read the [architecture](docs/architecture.md) and [security model](docs/security-model.md), especially the boundaries around authorization, isolation, cleanup, evidence, and auditability. Contributions must preserve the principle that assessments are authorized, scoped, and isolated.

## Proposing changes

For a substantial change, open an issue first to describe the problem, proposed approach, security implications, and affected components. Small documentation fixes may be submitted directly.

Keep changes focused. Update related documentation when behavior, interfaces, security requirements, or the roadmap changes.

## Security-sensitive changes

Do not include real credentials, private target information, production data, or undisclosed vulnerabilities in issues, commits, tests, or pull requests. Use synthetic targets and test data.

Changes affecting authorization, sandboxing, network restrictions, cleanup, secrets, authentication, project isolation, evidence, or audit events should include failure-path tests and explain how the security boundary is preserved. Report vulnerabilities privately as described in [`SECURITY.md`](SECURITY.md), rather than opening a public issue.

## Development expectations

Use Python 3.14 and an activated virtual environment. Install the development tools:

```bash
python -m pip install -e ".[test,quality,security]"
```

Run the same fast checks as CI:

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Tests set their own environment and use a temporary SQLite database, independent
of your `.env` and development data. For automatic import/lint fixes and formatting:

```bash
python -m ruff check --fix .
python -m ruff format .
```

Audit your development environment's installed dependencies with:

```bash
python -m pip_audit --skip-editable
```

The security workflow resolves runtime dependencies in a separate environment,
excluding test and audit tools from its report. It runs on PRs, pushes to `main`,
weekly, and on demand. Audit errors and known vulnerabilities fail the job.

For sandbox changes, run the [real Docker walkthrough](docs/getting-started.md)
and check that no assessment containers or networks remain. CI runs this on a
disposable Docker daemon and uploads verification output and diagnostic logs.

Development expectations:

- Use the repository's configured formatter, linter, and test commands.
- Run Python tools through the active environment (`python -m pytest` and
  `python -m uvicorn ...`) so Windows and Unix setups use the same interpreter.
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

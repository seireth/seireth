# Contributing to SEIRETH

Read the [Code of Conduct](CODE_OF_CONDUCT.md), [architecture](docs/architecture.md),
and [security model](docs/security-model.md). Preserve authorized, scoped,
isolated assessments and their cleanup, evidence, and audit guarantees.

## Proposing changes

Open an issue for substantial changes, describing the problem, approach, security
implications, and affected components. Small documentation fixes can go directly
to a PR. Keep changes focused; update docs for behavior, interfaces, security,
and roadmap changes.

Use synthetic targets/data. Never include credentials, private target information,
production data, or undisclosed vulnerabilities in issues, commits, tests, or PRs.
Report vulnerabilities privately through [SECURITY.md](SECURITY.md).

Changes affecting authorization, sandboxing/network restrictions, cleanup, secrets,
authentication, project isolation, evidence, or audit events should include
failure-path tests and explain how boundaries remain intact. Add tests for behavior
changes, handle authorization/cleanup/audit failures explicitly, and never weaken
secure defaults to pass checks. Keep generated files, databases, credentials,
and build output out of commits.

## Development setup

Follow [setup](docs/getting-started.md), then install tools in the activated
Python 3.14 environment. Use `python -m ...` for the same interpreter across platforms.

```bash
python -m pip install -e ".[test,quality,security]"
python -m ruff check .
python -m ruff format --check .
```

For automatic import/lint fixes and formatting:

```bash
python -m ruff check --fix .
python -m ruff format .
```

## Tests

Tests set their own environment. Each database-backed test creates and drops only
its uniquely named database. Explicitly configure `SEIRETH_TEST_ADMIN_URL` with
create-database permissions on a local/disposable PostgreSQL server, never an
operator/production database. Adjust these example credentials to your setup.

```powershell
# PowerShell
$env:SEIRETH_TEST_ADMIN_URL='postgresql+psycopg://seireth:seireth-local@127.0.0.1:5432/postgres'
python -m app test
```

```bash
# macOS / Linux
export SEIRETH_TEST_ADMIN_URL='postgresql+psycopg://seireth:seireth-local@127.0.0.1:5432/postgres'
python -m app test
```

`python -m pytest` is equivalent. CI runs unit/API tests and the Ruff checks above.
Windows defaults to a fresh `build/pytest-<unique-id>` per run to avoid shared-temp
permission errors; `--basetemp` overrides it. Artifacts remain in ignored `build/`.
Pure tests need no PostgreSQL:

```bash
python -m pytest tests/test_scope_urls.py tests/test_verify.py tests/test_docker_sandbox.py
```

For sandbox changes, run the [Docker walkthrough](docs/getting-started.md#real-docker-assessment),
check that no assessment containers/networks remain, then run lifecycle tests.
They require the built demo and pulled runner images; the demo's `/slow` path
briefly delays responses for cancellation/crash-recovery tests.

```powershell
# PowerShell, with SEIRETH_TEST_ADMIN_URL already set
$env:SEIRETH_DOCKER_TESTS='1'
python -m pytest tests/test_api_process.py
```

```bash
# macOS / Linux, with SEIRETH_TEST_ADMIN_URL already set
SEIRETH_DOCKER_TESTS=1 python -m pytest tests/test_api_process.py
```

CI uses a disposable Docker daemon and uploads verification output and diagnostic logs.

## Dependency audit

```bash
python -m pip_audit --skip-editable
```

This audits installed development dependencies. The security workflow separately
resolves runtime dependencies, excluding test/audit tools. It runs on PRs, pushes
to `main`, weekly, and on demand; audit errors and known vulnerabilities fail it.

## Schema changes

Add a revision after the current Alembic head in `app/migrations/versions`:

```bash
python -m alembic revision --autogenerate -m "describe schema change"
```

Review generated operations before applying them. Never edit deployed revisions,
including `0001_initial_schema`. Run `python -m app migrate` before native API
startup; the API neither checks revisions nor applies migrations. Docker startup
uses the [migration-gated command](docs/getting-started.md#real-docker-assessment).

## Pull requests

Explain what changed and why, tests performed, security/compatibility/migration/
operational impacts, and remaining documentation or follow-up work.
Contributions are licensed under the repository's Apache License 2.0.

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
secure defaults to pass checks. Keep databases, credentials, and build output out
of commits. Commit the generated dependency lock alongside its manifest.

## Development setup

Follow [setup](docs/getting-started.md), then synchronize the development extras.
Use `uv run --no-sync` to execute tools in the locked environment on every platform.

```bash
uv sync --locked --all-extras
uv run --no-sync python -m ruff check .
uv run --no-sync python -m ruff format --check .
```

For automatic import/lint fixes and formatting:

```bash
uv run --no-sync python -m ruff check --fix .
uv run --no-sync python -m ruff format .
```

## Tests

Tests set their own environment. Each database-backed test creates and drops only
its uniquely named database. Explicitly configure `SEIRETH_TEST_ADMIN_URL` with
create-database permissions on a local/disposable PostgreSQL server, never an
operator/production database. Adjust these example credentials to your setup.

```powershell
# PowerShell
$env:SEIRETH_TEST_ADMIN_URL='postgresql+psycopg://seireth:seireth-local@127.0.0.1:5432/postgres'
uv run --no-sync python -m app test
```

```bash
# macOS / Linux
export SEIRETH_TEST_ADMIN_URL='postgresql+psycopg://seireth:seireth-local@127.0.0.1:5432/postgres'
uv run --no-sync python -m app test
```

`uv run --no-sync python -m pytest` is equivalent. CI runs unit/API tests and
the Ruff checks above.
Windows defaults to a fresh `build/pytest-<unique-id>` per run to avoid shared-temp
permission errors; `--basetemp` overrides it. Artifacts remain in ignored `build/`.
Pure tests need no PostgreSQL:

```bash
uv run --no-sync python -m pytest tests/test_policy.py tests/test_verify.py tests/test_docker_sandbox.py
```

For sandbox changes, run the [Docker walkthrough](docs/getting-started.md#real-docker-assessment),
check that no assessment containers/networks remain, then run lifecycle tests.
They require the built demo and pulled runner images; the demo's `/slow` path
briefly delays responses for cancellation/crash-recovery tests.

```powershell
# PowerShell, with SEIRETH_TEST_ADMIN_URL already set
$env:SEIRETH_DOCKER_TESTS='1'
uv run --no-sync python -m pytest tests/test_api_lifecycle.py
```

```bash
# macOS / Linux, with SEIRETH_TEST_ADMIN_URL already set
SEIRETH_DOCKER_TESTS=1 uv run --no-sync python -m pytest tests/test_api_lifecycle.py
```

CI uses a disposable Docker daemon and uploads verification output and diagnostic logs.

## Dependency audit

```bash
uv run --no-sync python -m pip_audit --skip-editable
```

This audits installed development dependencies. The security workflow separately
exports runtime dependencies from `uv.lock`, excluding test/audit tools. It runs
on PRs, pushes to `main`, weekly, and on demand; audit errors and known
vulnerabilities fail it.

## Updating dependencies

`uv.lock` is committed and shared by development, CI, and Docker. Installs use
`--locked` and fail if the manifest and lock disagree. Third-party source builds
are disabled; missing wheels are errors, not a reason to bypass that policy.
The trusted Seireth package is still built with the exactly pinned setuptools backend.

After changing dependency declarations, run `uv lock`. For deliberate upgrades,
run `uv lock --upgrade-package PACKAGE` (or `uv lock --upgrade` for a full refresh),
then `uv sync --locked --all-extras`, checks, and the dependency audit. Commit the
manifest and lock together. Dependabot updates the uv ecosystem weekly.

Keep the exact uv version in the project configuration, both workflows, Dockerfile,
and setup instructions aligned when upgrading uv. No exported requirements file
is committed: the security workflow creates its runtime-only export temporarily.

## Schema changes

Add a revision after the current Alembic head in `app/migrations/versions`:

```bash
uv run --no-sync python -m alembic revision --autogenerate -m "describe schema change"
```

Review generated operations before applying them. Never edit deployed revisions,
including `0001_initial_schema`. Run `uv run --no-sync python -m app migrate` before native API
startup; the API neither checks revisions nor applies migrations. Docker startup
uses the [migration-gated command](docs/getting-started.md#real-docker-assessment).

## Pull requests

Explain what changed and why, tests performed, security/compatibility/migration/
operational impacts, and remaining documentation or follow-up work.
Contributions are licensed under the repository's Apache License 2.0.

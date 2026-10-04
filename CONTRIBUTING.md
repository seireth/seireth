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

Add tests for behavior changes. Keep databases, credentials, and build output out
of commits; commit the generated dependency lock alongside its manifest.

## Security-sensitive changes

Changes to authorization, scope, sandboxing, networking, cleanup, secrets,
runtime access, authentication, project or tenant isolation, evidence, reports,
audit integrity, or dependency, image and plugin execution must include
failure-path tests and explain how boundaries remain intact. Fail closed when
security prerequisites cannot be verified; handle failures explicitly and never
weaken secure defaults to pass checks.

## Development setup

Follow [setup and activation](docs/getting-started.md), then synchronize the development extras.
Activate once per terminal; all Python commands below use that environment.

```bash
uv sync --locked --python 3.14 --all-extras
python -m ruff check .
python -m ruff format --check .
```

For automatic import/lint fixes and formatting:

```bash
python -m ruff check --fix .
python -m ruff format .
```

## Tests

Backend tests mirror application modules: API resource tests live in `tests/api/`,
plugin tests in `tests/plugins/`, and application startup/serving tests in
`tests/test_main.py`. Process lifecycle tests live in `tests/integration/`.
Shared fixtures stay in `tests/conftest.py`; HTTP-specific fixtures live in
`tests/api/conftest.py`.

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

`python -m pytest` is equivalent. The build workflow runs non-Docker Python
tests with coverage; CI runs the Ruff checks above.
Windows defaults to a fresh `build/pytest-<unique-id>` per run to avoid shared-temp
permission errors; `--basetemp` overrides it. Artifacts remain in ignored `build/`.
Pure tests need no PostgreSQL:

```bash
python -m pytest -m "not database and not docker"
```

The `database` marker covers tests using the disposable database fixture and direct
database checks. `python -m pytest -m database` selects them; missing
`SEIRETH_TEST_ADMIN_URL` is an error. The `docker` marker identifies real Docker
cases; it does not enable them. Set `SEIRETH_DOCKER_TESTS=1` as shown below.

For sandbox changes, run the [Docker walkthrough](docs/getting-started.md#real-docker-assessment),
check that no assessment containers/networks remain, then run lifecycle tests.
They require the built demo and pulled runner images; the demo's `/slow` path
briefly delays responses for cancellation/crash-recovery tests.

```powershell
# PowerShell, with SEIRETH_TEST_ADMIN_URL already set
$env:SEIRETH_DOCKER_TESTS='1'
python -m pytest -m docker tests/integration/test_api_process_lifecycle.py
```

```bash
# macOS / Linux, with SEIRETH_TEST_ADMIN_URL already set
SEIRETH_DOCKER_TESTS=1 python -m pytest -m docker tests/integration/test_api_process_lifecycle.py
```

The integration workflow uses a disposable Docker daemon and uploads verification
output and diagnostic logs. It selects only Docker-marked Python cases; the
in-memory API lifecycle case runs once in the build workflow.

## Frontend checks

Follow the [Node/npm setup](docs/getting-started.md), then run:

```bash
npm --prefix app/web ci --ignore-scripts
npm --prefix app/web run lint
npm --prefix app/web run typecheck
npm --prefix app/web test
npm --prefix app/web run build
```

`build` bundles assets without checking TypeScript types. Run `typecheck`
separately before building locally; CI owns this check for pull requests.

For browser verification, start the
[Docker stack](docs/getting-started.md#real-docker-assessment), then:

```bash
npm --prefix app/web exec --ignore-scripts -- playwright install chromium
npm --prefix app/web run test:e2e
```

Set [`SEIRETH_UI_URL`](docs/configuration.md#gui-development) for a nondefault API address.
Set `SEIRETH_DOCKER_EXECUTABLE` to an absolute path for a nonstandard Docker CLI
installation. Browser cleanup checks invoke that executable directly, without
searching `PATH`.
The suite creates synthetic records and verifies six `/cookies` findings, linked
evidence, redaction, and Docker cleanup. Failure traces and screenshots are in
`app/web/test-results/`. On Linux, add `--with-deps` to the browser installation
command to install Chromium's system dependencies, as the integration workflow does.

Sonar classifies backend tests, frontend unit tests, and browser tests as test
code. The browser suite intentionally assesses the HTTP demo on Docker's private
network to exercise cookie-security violations; it does not use private targets
or transmit credentials.

### Coverage

With `SEIRETH_TEST_ADMIN_URL` configured, generate the same coverage reports as
the build workflow from the repository root:

```bash
python -m pytest -m "not docker" --cov --cov-config=pyproject.toml --cov-report=term-missing --cov-report=xml:coverage.xml
npm --prefix app/web test -- --coverage
```

Python coverage measures `app`, including Python subprocesses, with branch
coverage and relative source paths. Frontend coverage includes unimported source
files and excludes tests, test setup, and declarations. SonarQube imports
`coverage.xml` and `app/web/coverage/lcov.info`; Docker and browser runs do not
contribute to these reports. Generated coverage and analysis output stay untracked.

### Workflow ownership and required checks

All four workflows run independently on main pushes, pull requests, and manual
dispatch. Dependency audits also run weekly. Each test suite runs once per event;
the application image and bundled frontend are built in integration only.

| Workflow | Required job checks | Responsibility |
| --- | --- | --- |
| [CI](.github/workflows/ci.yml) | Repository checks; Python quality; Frontend quality | Required files, environment-file hygiene, Ruff, ESLint, TypeScript |
| [Build](.github/workflows/build.yml) | Tests, coverage and SonarQube | Non-Docker Python tests with disposable PostgreSQL, frontend unit tests, coverage, analysis |
| [Integration](.github/workflows/integration.yml) | Docker assessment lifecycle | Image build, migrations/readiness, real assessments/recovery, browser and packaging verification |
| [Dependency security](.github/workflows/security.yml) | Audit frontend dependencies; Audit Python runtime dependencies | Locked dependency audits |

Update repository rulesets/branch protection after these checks first appear.
Replace `Frontend quality and build` with `Frontend quality`, and `Python 3.14
tests` with `Tests, coverage and SonarQube`. The Docker job name stays `Docker
assessment lifecycle`, but now comes from the Integration workflow; update any
workflow-specific rule accordingly. Require all checks above before merging,
especially `Frontend quality`: successful bundling does not imply valid types.

SonarQube configuration lives in the build action arguments. Keep automatic
analysis disabled and configure the repository Actions secret `SONAR_TOKEN`.
After both test suites and report checks pass, the scanner waits up to 300 seconds
for the existing quality gate; scan errors, processing timeouts, or a failed gate
fail the build job. Fork pull requests and Dependabot runs execute tests but skip
SonarQube; other runs fail clearly if the token is missing. Diagnostics and
database cleanup run on failure, including analysis failures. Coverage generation
and scanning share a job and require no report transfer between workflows.

Build frontend assets before packaging. Clear setuptools' staging directory so
hashed assets from earlier builds cannot enter the wheel:

```powershell
# Windows, from the repository root
if (Test-Path build/lib) { Remove-Item -LiteralPath build/lib -Recurse -Force }
uv build --wheel
```

```bash
# macOS / Linux, from the repository root
rm -rf build/lib
uv build --wheel
```

Commit `package-lock.json` with dependency changes; keep generated assets,
`node_modules/`, and browser artifacts untracked.

Dependency installation disables package lifecycle scripts in local setup, CI,
and Docker. Run the project's build/test commands and Playwright browser
installation explicitly; do not re-enable dependency install hooks.

## Dependency audit

```bash
python -m pip_audit --skip-editable
npm --prefix app/web audit
```

This audits installed development dependencies. The [security workflow](.github/workflows/security.yml)
audits locked runtime dependencies, excluding test/audit tools, and fails on audit
errors or known vulnerabilities.

## Updating dependencies

`uv.lock` is committed and shared by development, CI, and Docker. Installs use
`--locked` and fail if the manifest and lock disagree. Third-party source builds
are disabled; missing wheels are errors, not a reason to bypass that policy.
The trusted Seireth package is still built with the exactly pinned setuptools backend.

After pulling dependency changes, run `uv sync --locked --all-extras`; runtime-only
sync can remove development tools. Direct Python commands do not synchronize.

After changing dependency declarations, run `uv lock`. For deliberate upgrades,
run `uv lock --upgrade-package PACKAGE` (or `uv lock --upgrade` for a full refresh),
then `uv sync --locked --all-extras`, checks, and the dependency audit. Commit the
manifest and lock together. [Dependabot configuration](.github/dependabot.yml)
defines update schedules and exclusions; Python minor/major and PostgreSQL major
upgrades are planned separately.

Keep the exact uv version in the project configuration, all workflows, Dockerfile,
and setup instructions aligned when upgrading uv.

## Schema changes

For subsequent incremental schema changes, add a revision after the current
Alembic head in `app/migrations/versions`:

```bash
python -m alembic revision --autogenerate -m "describe schema change"
```

Run `python -m app migrate` before native API startup; the API neither checks
revisions nor applies migrations. Docker startup
uses the [migration-gated command](docs/getting-started.md#real-docker-assessment).

## Pull requests

Explain what changed and why, tests performed, security/compatibility/migration/
operational impacts, and remaining documentation or follow-up work.
Contributions are licensed under the repository's Apache License 2.0.

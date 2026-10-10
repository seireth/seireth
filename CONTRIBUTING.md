# Contributing to SEIRETH

Read the [Code of Conduct](CODE_OF_CONDUCT.md), [architecture](docs/architecture.md),
and [security model](docs/security-model.md). Preserve project and URL boundaries,
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

Changes to project authorization, target boundaries, sandboxing, networking, cleanup, secrets,
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

Backend tests mirror application modules: `tests/api/`, `tests/assessments/`,
`tests/cli/`, `tests/core/`, `tests/persistence/`, and `tests/plugins/`.
Migration tests live in `tests/persistence/migrations/`; application
startup/serving tests stay in `tests/test_main.py`. Process lifecycle tests live
in `tests/integration/`. Frontend tests stay alongside the dashboard source.
Shared fixtures stay in `tests/conftest.py`; HTTP-specific fixtures live in
`tests/api/conftest.py`.

Tests set their own environment. Each database-backed test creates and drops only
its uniquely named database. Explicitly configure `SEIRETH_TEST_ADMIN_URL` with
create-database permissions on a local/disposable PostgreSQL server, never an
operator/production database. Adjust these example credentials to your setup.

```powershell
# PowerShell
$env:SEIRETH_TEST_ADMIN_URL='postgresql+psycopg://seireth:seireth-local@127.0.0.1:5432/postgres'
python -m pytest
```

```bash
# macOS / Linux
export SEIRETH_TEST_ADMIN_URL='postgresql+psycopg://seireth:seireth-local@127.0.0.1:5432/postgres'
python -m pytest
```

The build workflow runs non-Docker Python
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
npm --prefix app/dashboard ci --ignore-scripts
npm --prefix app/dashboard run lint
npm --prefix app/dashboard run typecheck
npm --prefix app/dashboard test
npm --prefix app/dashboard run build
```

`build` bundles assets without checking TypeScript types. Run `typecheck`
separately before building locally; CI owns this check for pull requests.

For browser verification, start the
[Docker stack](docs/getting-started.md#real-docker-assessment), then:

```bash
npm --prefix app/dashboard exec --ignore-scripts -- playwright install chromium
npm --prefix app/dashboard run test:e2e
```

Set [`SEIRETH_UI_URL`](docs/configuration.md#gui-development) for a nondefault API address.
Set `SEIRETH_DOCKER_EXECUTABLE` to an absolute path for a nonstandard Docker CLI
installation. Browser cleanup checks invoke that executable directly, without
searching `PATH`.
The suite creates synthetic records and verifies six `/cookies` findings, linked
evidence, redaction, and Docker cleanup. Failure traces and screenshots are in
`app/dashboard/test-results/`. On Linux, add `--with-deps` to the browser installation
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
npm --prefix app/dashboard test -- --coverage
```

Python coverage measures `app`, including Python subprocesses, with branch
coverage and relative source paths. The demo application is excluded from Python
and SonarQube coverage; its unit tests guard against false verification success.
Frontend coverage includes unimported source files and excludes tests, test setup,
and declarations. SonarQube imports
`coverage.xml` and `app/dashboard/coverage/lcov.info`; Docker and browser runs do not
contribute to these reports. Generated coverage and analysis output stay untracked.

### Workflow ownership and required checks

All three workflows run independently on main pushes, pull requests, and manual
dispatch. Dependency Review runs only on pull requests. Each test suite runs once
per event; the application image and bundled frontend are built in integration only.

Runtime setup and SonarQube configuration stay inline. External actions use commit
pins with release comments. The two database jobs generate and mask fresh
credentials inline, then export them through `GITHUB_ENV`; no credential helper
script is required. Python syncs explicitly use `--no-build`; the quality job also
uses `--no-install-project` because it only needs dependencies and tools.

| Workflow                                         | Required job checks                                                    | Responsibility                                                                                    |
| ------------------------------------------------ | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| [CI](.github/workflows/ci.yml)                   | Repository checks; Python quality; Frontend quality; Dependency review | Required files, environment-file hygiene, Ruff, ESLint, TypeScript, vulnerable dependency changes |
| [Build](.github/workflows/build.yml)             | Tests, coverage and SonarQube                                          | Non-Docker Python tests with disposable PostgreSQL, frontend unit tests, coverage, analysis       |
| [Integration](.github/workflows/integration.yml) | Docker assessment lifecycle                                            | Image build, migrations/readiness, real assessments/recovery, browser and packaging verification  |

Require all six checks above before merging, with GitHub Actions as their source.
Successful bundling does not imply valid types; keep `Frontend quality` required.
See [Dependency security](#dependency-security) for the repository settings and
rollout checks. Workflow YAML alone does not enforce merge requirements.

SonarQube configuration lives in the build action arguments. Keep automatic
analysis disabled and configure a valid project analysis token named `SONAR_TOKEN`
in both repository Actions secrets and Dependabot secrets. Add the latter under
**Settings > Secrets and variables > Dependabot > New repository secret**.
Dependabot-triggered workflows use Dependabot secrets through the same
`${{ secrets.SONAR_TOKEN }}` reference; ordinary runs use Actions secrets. See
[GitHub's secret access documentation](https://docs.github.com/en/code-security/reference/supply-chain-security/troubleshoot-dependabot/dependabot-on-actions#accessing-secrets).

After both test suites and report checks pass, the scanner submits the analysis.
Keep `SonarCloud Code Analysis` required in `Protect main`, with SonarCloud as its
source, so its quality gate also blocks merging. Missing tokens or scanner errors
fail the build job. Same-repository pull requests, including Dependabot, run
SonarQube; fork pull requests execute tests but skip the token check and scan.
Diagnostics and database cleanup run on failure, including analysis failures.
Coverage generation and scanning share a job and require no report transfer
between workflows.

After merging changes to these workflow conditions, rebase existing Dependabot
pull requests by commenting `@dependabot rebase` on each PR. Verify all six job
checks and `SonarCloud Code Analysis` pass on the new head before merging.

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

## Dependency security

The CI job `Dependency review` rejects pull requests that introduce dependencies
with known vulnerabilities of low severity or higher. It includes runtime,
development, and unknown scopes, compares the PR's base and head dependencies,
and does not install packages. License checks and PR comments are disabled;
results appear in the job logs and summary.

Dependabot alerts monitor vulnerabilities in dependencies already on the default
branch, including newly published advisories. Such alerts do not automatically
block unrelated pull requests. Dependabot security updates propose fixes when
available; the schedules in `.github/dependabot.yml` control version-update PRs
separately. Review alerts and update PRs regularly.

Configure and verify these settings on GitHub:

1. Under **Settings > Security and quality > Advanced Security**, enable the
   dependency graph, Dependabot alerts, and Dependabot security updates. Confirm
   Python and npm dependencies, including transitive packages, appear under
   **Insights > Dependency graph**.
2. Run Dependency Review on PRs changing each lockfile. Check that the comparison
   contains the expected Python and npm changes; an empty result is not evidence
   of coverage. Verify a known vulnerable change fails before retiring the audits.
3. Under **Settings > Rules > Rulesets > Protect main**, replace the two former
   audit requirements with `Dependency review` once that check has run successfully.
   Keep the other five checks listed above and select GitHub Actions as the source.
4. Keep pull requests required, set required approving reviews to zero for solo
   maintenance, and remove the administrator bypass so all six checks apply to
   everyone. Preserve the remaining rules and the separate `Cant commit to main`
   ruleset. Confirm a failed check blocks merging before considering rollout complete.

GitHub's [Dependency Review action](https://github.com/actions/dependency-review-action)
and [dependency graph documentation](https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-graph-data)
describe the comparison and dependency coverage.

## Updating dependencies

`uv.lock` is committed and shared by development, CI, and Docker. Installs use
`--locked` and fail if the manifest and lock disagree. Third-party source builds
are disabled; missing wheels are errors, not a reason to bypass that policy.
The trusted Seireth package is still built with the exactly pinned setuptools backend.

After pulling dependency changes, run `uv sync --locked --all-extras`; runtime-only
sync can remove development tools. Direct Python commands do not synchronize.

After changing dependency declarations, run `uv lock`. For deliberate upgrades,
run `uv lock --upgrade-package PACKAGE` (or `uv lock --upgrade` for a full refresh),
then `uv sync --locked --all-extras` and the local checks. Commit the manifest and
lock together; Dependency Review runs on the pull request. [Dependabot configuration](.github/dependabot.yml)
defines update schedules and exclusions; Python minor/major and PostgreSQL major
upgrades are planned separately.

Keep the exact uv version in the project configuration, all workflows, Dockerfile,
and setup instructions aligned when upgrading uv.

## Schema changes

For subsequent incremental schema changes, add a revision after the current
Alembic head in `app/persistence/migrations/versions`:

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

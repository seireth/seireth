# Lifecycle acceptance

These checks use the existing FastAPI dispatcher, Python Docker sandbox, and
React/Vite dashboard. They run against disposable PostgreSQL databases and the
owned demo image, without editing assessment rows to advance their status.

## Prepare

Install the test dependencies described in [Contributing](../CONTRIBUTING.md).
Start Docker, build the fixture, and provide a PostgreSQL admin connection that
may create and drop disposable databases:

```powershell
docker build -t seireth/demo-app:local examples/demo_app
docker build --target runner -t seireth/runner:local .
$env:SEIRETH_TEST_ADMIN_URL = "postgresql+psycopg://user:password@127.0.0.1:5432/postgres"
$env:SEIRETH_DOCKER_TESTS = "1"
$env:PYTHONPATH = (Get-Location).Path
uv run --no-sync --no-build python -m pytest tests/integration/test_api_process_lifecycle.py
```

The Docker tests remain opt-in. Each assessment labels its network and containers
with the assessment and attempt IDs. The acceptance checks verify persisted
cleanup and independently inspect Docker for remaining resources.

## What is proved

| Case | Expected result | Proof |
| --- | --- | --- |
| `/lab/nosniff-first-invalid` | Completed, one MIME protection finding | A real HTTP response reaches the existing `http-security-headers` plugin; its finding links to retrievable evidence. |
| `/lab/nosniff-first-valid` | Completed, zero findings | The corrected fixture passes the same selected plugin. |
| Plugin crash | Failed with `plugin_error` and `failed_plugin` | A test-only analyzer raises after the real sandbox fetch; no partial findings are published, and cleanup is verified. |
| Analyzer overrun | Failed with `timeout` | A test-only bounded analyzer returns after the deadline following the real sandbox fetch; cleanup is then verified. This proves overrun classification. |
| Duplicate delivery | One attempt | Repeated dispatcher submissions cannot start another active execution. The worker concurrency regression also exercises independent duplicate claims. |
| API/worker restart | Same saved findings, evidence, and provenance | Fresh lifespans and a separate API process retrieve the report without rerunning completed work. Installed plugin versions may change without altering the saved report. |

The injected crash and delay plugins exist only inside tests. Production uses the
approved built-in registry. Plugins execute synchronously and must keep analysis
bounded; an analyzer that never returns cannot be forcibly interrupted by the
current worker.

Deadline interruption is tested separately with the sandbox's actual subprocess
reaping code: a blocked runner is killed before cleanup starts, and the test
daemon verifies removal of every owned resource. This deterministic check needs
no Docker daemon:

```powershell
uv run --no-sync --no-build python -m pytest tests/assessments/test_sandbox.py -k "subprocess"
```

The existing process tests also cover cancellation, hard process failure,
verified cleanup before a recovery retry, and removal of the target image before
recovery. Schema checks cover fresh creation, downgrade/recreation, and mandatory execution
and route provenance:

```powershell
uv run --no-sync --no-build python -m pytest tests/assessments/test_worker.py tests/persistence/migrations/test_migrations.py tests/api/test_reports.py
```

## Inspect the same run

Start the updated API after `alembic upgrade head`, with
the dashboard built and the current runner image prepared. Register a project and
the fixture target at `http://demo-app:8080/`, select `http-security-headers`, and
submit either fixture URL above. The assessment detail page polls until terminal,
shows the execution reason and cleanup separately, and exposes evidence and JSON
or offline HTML downloads. Reload preserves persisted results.

The detail view and HTML report display the recorded start, deadline, and plugin
versions. Failed and cancelled reports explicitly identify incomplete execution.
Export time and later cleanup reconciliation may change between report reads;
the executed target, versions, findings, and evidence remain persisted.

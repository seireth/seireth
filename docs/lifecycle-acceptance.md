# Lifecycle acceptance

These checks run against disposable PostgreSQL databases and real Docker
resources. Assessment states advance through the dispatcher.

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

Tests inspect Docker independently of persisted cleanup outcomes.

## What is proved

| Case | Expected result | Proof |
| --- | --- | --- |
| `/lab/nosniff-first-invalid` | Completed, one MIME protection finding | A real HTTP response reaches the existing `http-security-headers` plugin; its finding links to retrievable evidence. |
| `/lab/nosniff-first-valid` | Completed, zero findings | The corrected fixture passes the same selected plugin. |
| Plugin crash | Failed with `plugin_error` and `failed_plugin` | A test-only analyzer raises after the real sandbox fetch; no partial findings are published, and cleanup is verified. |
| Analyzer overrun | Failed with `timeout` | A test-only bounded analyzer returns after the deadline following the real sandbox fetch; cleanup is then verified. This proves overrun classification. |
| Duplicate delivery | One attempt | Repeated dispatcher submissions cannot start another active execution. The worker concurrency regression also exercises independent duplicate claims. |
| API/worker restart | Same saved findings, evidence, and provenance | Fresh lifespans and a separate API process retrieve the report without rerunning completed work. Installed plugin versions may change without altering the saved report. |

Injected crash/delay plugins are test-only. Synchronous analysis cannot be
forcibly interrupted; the timeout case proves overrun classification.

Deterministic subprocess tests verify a blocked runner is killed before cleanup,
without requiring Docker:

```powershell
uv run --no-sync --no-build python -m pytest tests/assessments/test_sandbox.py -k "subprocess"
```

Worker, migration, and report tests cover cancellation, recovery, fresh schema
creation, mandatory provenance, and report retrieval:

```powershell
uv run --no-sync --no-build python -m pytest tests/assessments/test_worker.py tests/persistence/migrations/test_migrations.py tests/api/test_reports.py
```

For manual dashboard inspection and report downloads, use
[getting started](getting-started.md#real-docker-assessment) and
[the assessment guide](assessments.md#download-assessment-reports).

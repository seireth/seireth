# Getting started

Use Python 3.14 for local development and CI. Docker Desktop (Linux containers)
or Docker Engine with Compose is needed only for real sandbox execution.

## Install

Clone the repository and enter its root. On Windows PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

On macOS or Linux:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
cp .env.example .env
```

Then, on either platform:

```bash
python --version
python -m pip install -e ".[test,quality,security]"
python -m pytest
python -m app serve
```

The API runs at `http://127.0.0.1:8000`. Visit `/health`, `/docs` for the API
explorer, or `/openapi.json` for the generated contract. Keep this terminal
running and activate the same environment in a second terminal:

```bash
python -m app verify --expected-backend inmemory
```

Verification creates a project, target, expiring scope, and assessment; waits
for completion; and checks findings, cleanup status, and audit ordering. It
prints the records as JSON. Repeated verification creates additional records.
The in-memory backend returns empty simulated headers and makes no requests.

## Docker walkthrough

Stop the development API first so port 8000 is available. From the repository
root with `.env` present:

```bash
docker version
docker build -t seireth/demo-target:local examples/demo-target
docker pull python:3.14-slim
docker compose up --build -d
docker compose logs api
python -m app verify --expected-backend docker --timeout-seconds 120
docker compose down
```

Wait for the API startup message before verification. Compose overrides the
backend to `docker` and uses a named SQLite volume. Each assessment gets its
own internal network, target container, and short-lived runner. The worker
removes those resources after execution. `docker compose down` stops the API
and retains its data volume; adding `--volumes` deliberately deletes that data.

The verifier waits up to 120 seconds for an assessment outcome by default.
`--timeout-seconds` changes that polling deadline, not the worker's execution
limits. A verifier timeout does not cancel an assessment: inspect it using the
reported ID and [assessment endpoints](assessments.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Missing configuration fields | Run from the repository root and copy `.env.example` to `.env`. |
| Wrong Python or missing packages | Check `python --version`; activate `.venv` and install the development extras. |
| Port already occupied | Stop the local API before starting Compose. For local serving, use `python -m app serve --port 8001` and verify with `--base-url http://127.0.0.1:8001`. |
| Docker daemon unavailable | Start Docker Desktop, select Linux containers, and confirm `docker version` shows a server. |
| Target rejected | The default or requested image must appear exactly in the image allowlist. |
| Docker assessment fails | Build the target, pre-pull the runner, inspect `docker compose logs api`, and retrieve the assessment result. |
| Cleanup failed | Inspect remaining assessment containers and networks; see the [security model](security-model.md) before removing resources. |

For development checks, see [Contributing](../CONTRIBUTING.md).

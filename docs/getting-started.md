# Getting started

Run commands from the repository root. Start Docker Desktop/Engine with Linux
containers. Choose the setup section for your OS; uv uses Python 3.14 (downloading
it if needed) and installs dependencies in `.venv`. Stop if a command fails.

For the native GUI, install Node **24.16.0** and npm **11.13.0**, then build once
before starting the API. In PowerShell, use `npm.cmd` wherever this guide shows
`npm` to avoid execution-policy restrictions on `npm.ps1`:

```bash
npm install --global --ignore-scripts npm@11.13.0
npm --prefix app/dashboard ci --ignore-scripts
npm --prefix app/dashboard run typecheck
npm --prefix app/dashboard run build
```

`typecheck` validates TypeScript; `build` only bundles assets. Run both for local
verification.

`docker-up` builds the GUI automatically. Native API startup works without assets,
but `/dashboard/` returns 503. Build the assets and restart the native API to enable it.

## Windows PowerShell

Install uv once per computer; skip if `uv --version` already reports 0.12.23:

```powershell
$installer = Invoke-RestMethod 'https://astral.sh/uv/0.12.23/install.ps1'
Invoke-Expression $installer
```

Open a new terminal, return to the repository, then run:

```powershell
uv sync --locked --python 3.14
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\Activate.ps1
```

## macOS / Linux (Bash or Zsh)

Install uv once per computer; skip if `uv --version` already reports 0.12.23:

```bash
curl -LsSf https://astral.sh/uv/0.12.23/install.sh | sh
```

Open a new terminal, return to the repository, then run:

```bash
uv sync --locked --python 3.14
test -f .env || cp .env.example .env
source .venv/bin/activate
```

## Native startup

In the activated terminal, start PostgreSQL, apply pending migrations, and start
the API:

```bash
docker compose up -d --wait postgres
python -m app migrate
python -m app serve
```

For later starts, activate the existing `.venv` for your OS and repeat these three
commands. Applying migrations again is safe when the schema is already current.

## Simulated assessment

`serve` stays running in the terminal. With the example `.env`, open
http://127.0.0.1:8000/dashboard/. Create a project, register an explicit image and base URL,
then choose an **Assessment URL** and plugins on **New assessment**. Records can be reused; editing and deletion are
not available. The example uses simulated responses (`inmemory`) and PostgreSQL.
The JSON API explorer remains at `/docs`.
Setup preserves an existing `.env`; customized settings may differ.

In a **second terminal**, return to the repository and activate `.venv` using
`.\.venv\Scripts\Activate.ps1` (Windows) or `source .venv/bin/activate` (macOS/Linux).
Then run:

```bash
python -m app verify --image sample:local --target-url http://sample:8080/ --plugins http-security-headers --expected-backend inmemory
```

Stop the API with Ctrl+C. `docker compose down` stops the database and retains its
volume. See [Assessments](assessments.md) for individual requests.

## Real Docker assessment

Stop the native API with Ctrl+C first. In an activated terminal, prepare the demo
and runner images once (rebuild the demo after changing its source):

```bash
docker build -t seireth/demo-app:local examples/demo_app
docker pull python:3.14-slim
```

Then start and verify the Docker stack:

```bash
python -m app docker-up
python -m app verify --image seireth/demo-app:local --target-url http://demo-app:8080/cookies --plugins http-security-headers cookie-security --expected-backend docker
```

Verification checks findings, evidence associations, cleanup, and the audit trail;
its JSON output includes `results` and `evidence`.

`docker-up` builds the API, detects the Docker socket group for its non-root user,
waits for PostgreSQL, applies migrations, and waits for API health. Compose selects
the Docker backend; `--expected-backend` only checks results. Use `docker-up` for
startup: plain `docker compose up` skips migrations and socket-group detection.
Open `/dashboard/` on the configured API address for real assessments; choose the
demo's `http://demo-app:8080/cookies` URL and both plugins for six findings.
Stop with `docker compose down` before returning to native startup; this retains
the database volume.

For a working application with protected and deliberately misconfigured pages,
JSON, static assets, redirects, and errors, use the
[Northstar Workspace demo](../examples/demo_app/README.md). Its verifier creates
one saved project and target, and checks 36 header cases plus cookie cases with
individual and combined plugin selections through real Docker assessments.

## Fresh database baseline

This target API replaces the former authorization-scope schema. Initialize a fresh
database; upgrading an existing populated database is unsupported. The initial
migration has a required assessment URL and no authorization-scope table. If you
choose to discard local records, stop the stack and verify its Compose project and
PostgreSQL volume labels before removing only that database volume. Never prune
unrelated resources. Apply migrations before starting the updated API.

## After pulling changes

Stop the API first. If dependencies changed, run `uv sync --locked --python 3.14`.
Both [native startup](#native-startup) and `docker-up` apply pending migrations.
If the frontend lockfile changed, run `npm --prefix app/dashboard ci --ignore-scripts`
first. After frontend changes, run `npm --prefix app/dashboard run typecheck`, then
`npm --prefix app/dashboard run build` for native startup or `docker-up` for Docker.
Contributors should use `--all-extras` for Python setup and updates; see
[Contributing](../CONTRIBUTING.md) for tests, audits, and dependency updates.

## Frontend development

Keep the native API running in one terminal. In another:

```bash
npm --prefix app/dashboard ci --ignore-scripts
npm --prefix app/dashboard run dev
```

Open `http://127.0.0.1:5173/dashboard/`. Vite proxies `/api` and `/health` to the API.
If its address differs from the [proxy default](configuration.md#gui-development),
set `SEIRETH_UI_API_URL` before starting Vite.

## Troubleshooting

- **uv not found:** reopen the terminal or its hosting app. For this PowerShell
  session, try `$env:Path = "$HOME\.local\bin;$env:Path"`. On macOS/Linux, try
  `source "$HOME/.local/bin/env"` if that file was created by the installer.
- **Activation blocked:** replace `python` with `.\.venv\Scripts\python.exe` on
  Windows or `./.venv/bin/python` on macOS/Linux in the commands above.
- **Docker/startup failure:** check `docker info`, `docker compose ps -a`, and
  `docker compose logs postgres api`. Stop any other Seireth API using the same
  database or port; never force-unlock a live dispatcher.

For native PostgreSQL, set its `postgresql+psycopg://` URL in `.env` and skip Compose
database commands. See [Configuration](configuration.md) for settings/timeouts and
[Security model](security-model.md#cleanup-and-failure) for sandbox cleanup failures.

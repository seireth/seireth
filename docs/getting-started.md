# Getting started

Run commands from the repository root. Start Docker Desktop/Engine with Linux
containers. Choose the setup section for your OS; uv uses Python 3.14 (downloading
it if needed) and installs dependencies in `.venv`. Stop if a command fails.

For the native GUI, install Node **24.16.0** and npm **11.13.0**, then build once
before starting the API:

```bash
npm install --global --ignore-scripts npm@11.13.0
npm --prefix app/web ci --ignore-scripts
npm --prefix app/web run typecheck
npm --prefix app/web run build
```

`typecheck` validates TypeScript; `build` only bundles assets. Run both for local
verification. The CI workflow owns type checking, while Docker integration owns
the application build.

`docker-up` builds the GUI automatically. Native API startup works without assets,
but `/app/` returns 503. Build the assets and restart the native API to enable it.

## Windows PowerShell

### First-time setup

Install uv once per computer; skip if `uv --version` already reports 0.12.21:

```powershell
$installer = Invoke-RestMethod 'https://astral.sh/uv/0.12.21/install.ps1'
Invoke-Expression $installer
```

Open a new terminal, return to the repository, then run:

```powershell
uv sync --locked --python 3.14
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\Activate.ps1
docker compose up -d --wait postgres
python -m app migrate
python -m app serve
```

### Starting again later

```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d --wait postgres
python -m app serve
```

## macOS / Linux (Bash or Zsh)

### First-time setup

Install uv once per computer; skip if `uv --version` already reports 0.12.21:

```bash
curl -LsSf https://astral.sh/uv/0.12.21/install.sh | sh
```

Open a new terminal, return to the repository, then run:

```bash
uv sync --locked --python 3.14
test -f .env || cp .env.example .env
source .venv/bin/activate
docker compose up -d --wait postgres
python -m app migrate
python -m app serve
```

### Starting again later

```bash
source .venv/bin/activate
docker compose up -d --wait postgres
python -m app serve
```

## Simulated assessment

`serve` stays running in the terminal. With the example `.env`, open
http://127.0.0.1:8000/app/. Create a project, register a target, create a scope,
and select plugins on **New assessment**. The default scope lasts 15 minutes;
expiry inputs use local time. Records can be reused; editing and deletion are
not available. The example uses simulated responses (`inmemory`) and PostgreSQL.
The JSON API explorer remains at `/docs`.
The setup copy preserves an existing `.env`; customized settings may differ.

In a **second terminal**, return to the repository and activate `.venv` using
`.\.venv\Scripts\Activate.ps1` (Windows) or `source .venv/bin/activate` (macOS/Linux).
Then run:

```bash
python -m app verify --expected-backend inmemory
```

Stop the API with Ctrl+C. `docker compose down` stops the database and retains its
volume. See [Assessments](assessments.md) for individual requests.

## Real Docker assessment

Stop the native API with Ctrl+C first. In an activated terminal, prepare the demo
and runner images once (rebuild the demo after changing its source):

```bash
docker build -t seireth/demo-target:local examples/demo-target
docker pull python:3.14-slim
```

Then start and verify the Docker stack:

```bash
python -m app docker-up
python -m app verify --expected-backend docker
```

Verification checks findings, evidence associations, cleanup, and the audit trail;
its JSON output includes `results` and `evidence`.

`docker-up` builds the API, detects the Docker socket group for its non-root user,
waits for PostgreSQL, applies migrations, and waits for API health. Compose selects
the Docker backend; `--expected-backend` only checks results. Use `docker-up` for
startup: plain `docker compose up` skips migrations and socket-group detection.
Open `/app/` on the configured API address for real assessments; choose the
demo's `http://demo-target:8080/cookies` URL and both plugins for six findings.
Stop with `docker compose down`
before returning to native startup; this retains the database volume.

## After pulling changes

Stop the API first. If dependencies changed, run `uv sync --locked --python 3.14`.
If migrations changed, start PostgreSQL and run `python -m app migrate` before
native startup. `docker-up` handles migrations for Docker startup.
Contributors should use `--all-extras` for setup and updates; see
[Contributing](../CONTRIBUTING.md) for tests, audits, and dependency updates.
After frontend changes, run `npm --prefix app/web run typecheck`, then
`npm --prefix app/web run build` for native startup or `docker-up` for Docker.
Run `npm --prefix app/web ci --ignore-scripts` when the lockfile changes.

## Frontend development

Keep the native API running in one terminal. In another:

```bash
npm --prefix app/web ci --ignore-scripts
npm --prefix app/web run dev
```

Open `http://127.0.0.1:5173/app/`. Vite proxies `/api` and `/health` to the API.
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

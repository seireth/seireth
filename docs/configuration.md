# Configuration

Application settings use the `SEIRETH_` prefix. Environment variables take
precedence over `.env` in the current working directory, which takes precedence
over application defaults. Copy the committed `.env.example` before serving
or verifying the API; never commit your local `.env`.

## Settings

All names below include the `SEIRETH_` prefix.

| Setting | Default / requirement | Purpose |
| --- | --- | --- |
| `API_HOST` | Required; example `127.0.0.1` | Local CLI bind host and verifier URL |
| `API_PORT` | Required; example `8000` | Local CLI port and verifier URL |
| `ENVIRONMENT` | Required; example `local` | Environment label; does not itself enforce a security boundary |
| `SANDBOX_BACKEND` | Required; `inmemory` or `docker` | Select execution backend |
| `DATABASE_URL` | `sqlite:///./seireth.db` | SQLAlchemy connection URL |
| `DOCKER_TARGET_IMAGE` | Required | Image used when a target request omits `image` |
| `DOCKER_ALLOWED_TARGET_IMAGES` | Required JSON array | Accepted target image references |
| `DOCKER_RUNNER_IMAGE` | `python:3.14-slim` | Runner image controlled by the operator |
| `DOCKER_MEMORY` | `256m` | Container memory limit |
| `DOCKER_CPUS` | `0.5` | Container CPU quota |
| `DOCKER_PIDS_LIMIT` | `64` | Container process limit |
| `DOCKER_TIMEOUT_SECONDS` | `15` | Docker command timeout in seconds |

Docker target settings are required even when using the in-memory backend;
target registration applies the image policy for both backends.

## Default image and allowlist

```dotenv
SEIRETH_DOCKER_TARGET_IMAGE=seireth/demo-target:local
SEIRETH_DOCKER_ALLOWED_TARGET_IMAGES=["seireth/demo-target:local"]
```

The default selects an image; the allowlist decides whether that selection is
permitted. Requests may specify another image only if its exact reference is
listed. The default must also be listed. An empty list rejects all targets.

The allowlist enforces the server operator's policy on API requests. Someone
who controls the source or configuration can change that policy. Open-source
availability does not let a remote request edit the deployed configuration.
Listing an image does not prove that it is safe. Prefer immutable digests when
reproducible image identity matters; local demo tags are mutable.

Existing target records retain their selected image. The current implementation
checks the allowlist at registration, not again before each execution. Changing
the list is therefore not a revocation mechanism for previously registered targets.

## CLI and Compose overrides

`python -m app serve --host ... --port ...` overrides local CLI binding.
`python -m app verify --base-url ... --timeout-seconds 120 --expected-backend docker`
selects the API, polling deadline, and optional backend assertion.

Compose loads `.env`, then explicitly sets the Docker backend, runner image,
and SQLite location. The container command binds `0.0.0.0:8000`; the Compose
port mapping publishes port 8000 on the host. Local CLI bind settings do not
change that mapping. Keep this privileged MVP on a trusted development machine.

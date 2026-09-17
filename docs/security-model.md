# Security model

SEIRETH MVP-0 is a local, single-operator development tool. Run only images and
targets you own or are explicitly authorized to assess. Report vulnerabilities
using [SECURITY.md](../SECURITY.md).

## Implemented controls

- Project ownership checks use one fixed development actor.
- Authorization scopes are bounded to a target origin/path and checked for
  expiry at scope creation and assessment submission.
- Target registration accepts only image references on the operator's allowlist.
- Docker assessments create an internal network and do not publish target ports.
- Target and runner containers have read-only root filesystems, dropped Linux
  capabilities, no-new-privileges, CPU/memory/PID limits, and a restricted `/tmp`.
- Targets use an unprivileged numeric user. The runner currently uses its image's
  default user. Neither receives the Docker socket.
- Plugin execution is followed by cleanup, and outcome records include cleanup status.

## Trust boundaries and limitations

The API container mounts the host Docker socket. Control of this API process
can grant substantial control over the Docker host. The image allowlist does
not mitigate a compromised operator account or Docker daemon.

The API has no production authentication, tenant isolation, or TLS setup. Compose
publishes port 8000 using the host's default bind behavior. Do not expose it to
untrusted networks. Source-code scope checks are not proof of target ownership.

Docker containers share a kernel and are not a sufficient boundary for arbitrary
hostile workloads. Image tags are mutable. Allowlist changes are checked on new
registrations and do not revoke images already stored on targets.

The in-memory backend simulates responses and offers no real target isolation
or security measurement. The header plugin checks presence of three headers;
it does not validate their values or comprehensively assess application security.

Cancellation is cooperative. Scope expiry is checked when work is submitted,
not continuously during execution. Startup recovery may requeue unfinished work;
it does not reconcile all resources left by a process crash. Audit events are
application records, not cryptographically tamper-proof evidence.

## Cleanup and operator checks

The Docker backend attempts to remove its runner, target, and network, then
checks that the network cannot be inspected. The current cleanup boolean does
not independently inspect both containers after removal. Docker CI adds a
separate check that no assessment containers or networks remain.

For failures or interrupted runs, inspect:

```bash
docker ps -a --filter name=seireth-target- --filter name=seireth-assessment-runner-
docker network ls --filter name=seireth-assessment-
docker compose logs api
```

Match resources to the affected run and confirm they are no longer needed before
removing them by exact name. Do not use a global Docker prune on a shared daemon.
Treat `cleanup_verified: false` or a missing result as requiring investigation.

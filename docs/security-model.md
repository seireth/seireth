# Security model

SEIRETH is a local, single-operator development tool. Run only owned or explicitly
authorized images. The fixed development actor is not production authentication.
API and database ports bind to loopback; do not expose this deployment to untrusted
networks. Report vulnerabilities through [SECURITY.md](../SECURITY.md).

## Enforced boundaries

Admission and execution check project/target/scope relationships, origin/path,
expiry, passive profile, and the operator's image allowlist. Root URL scopes include
child paths; traversal, credentials, fragments, and ambiguous multiply encoded
paths are rejected. Redirect responses are inspected without following them.

The runner maps the registered host to the disposable target's Docker alias. It
measures the cloned image instance, not the original remote host. HTTPS targets
must have certificates valid for the sandbox alias; custom hostname/TLS mapping
is not implemented.

Targets and runners use a private internal network, no published ports, a non-root
numeric user, dropped capabilities, no-new-privileges, read-only filesystems, and
CPU/memory/PID limits. Neither gets the Docker socket. Scope expiry and cancellation
interrupt actual runner operations. Cleanup independently verifies each resource.

## Privileged and remaining boundaries

The API itself has the host Docker socket and therefore substantial host control.
The image allowlist does not protect a compromised API process, operator, or Docker
daemon. Containers share a kernel and are not appropriate for arbitrary hostile
workloads. Source-code scope checks do not prove target ownership. Image tags are
mutable. There is no multi-user authentication, tenant isolation, or production TLS.

The in-memory backend simulates headers without network access. The current plugin
checks only three header presences; it does not validate values or prove security.
Audit events are application records, not tamper-proof evidence.

## Cleanup and failure

Each resource carries assessment/attempt labels and has a persisted name. Cleanup
checks ownership before removal and uses successful enumeration to verify absence.
Docker errors, permissions failures, timeouts, or ownership mismatches never mean
successful cleanup. Mismatched resources are left untouched and reported unverified.

A terminal `cancelled` result after execution requires verified cleanup. Unverified
cleanup produces `failed` with `cleanup_verified: false`; startup revisits cleanup
without retrying that assessment. Crash-interrupted work is retried once only after
verified cleanup and renewed policy checks. An unknown cleanup outcome requires
operator investigation even though execution has stopped.

Inspect affected resources using exact labels/names:

```bash
docker ps -a --filter label=seireth.assessment=ASSESSMENT_ID
docker network ls --filter label=seireth.assessment=ASSESSMENT_ID
docker compose logs api
```

Do not use global Docker prune on a shared daemon.

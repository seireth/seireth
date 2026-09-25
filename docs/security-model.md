# Security model

SEIRETH is a local, single-operator development tool for owned or explicitly
authorized images. The fixed development actor provides no production
authentication. Example API/database bindings use loopback; a non-loopback API
binding exposes an unauthenticated service. Keep it off untrusted networks.
Report vulnerabilities through [SECURITY.md](../SECURITY.md).

## Enforced boundaries

Admission and execution check project/target/scope relationships, origin/path,
expiry, plugins, and image policy. Root URL scopes include child paths; traversal,
credentials, fragments, and ambiguous multiply encoded paths are rejected.
Redirect responses are inspected without following them.

The runner replaces the registered hostname with Docker alias `target`, measuring
the disposable image instance. HTTPS certificates must be valid and trusted for
that alias; custom hostname/TLS mapping is unsupported.

Targets and runners have an internal network, no published ports or Docker socket,
a non-root numeric user, dropped capabilities, no-new-privileges, read-only
filesystems, and CPU/memory/PID limits. Scope expiry and cancellation interrupt
runner operations; cleanup independently verifies each resource.

## Privileged and remaining boundaries

The API's Docker socket grants substantial host control. Allowlisting cannot
protect a compromised API, operator, or daemon. Tags are mutable; containers share
a kernel and are unsuitable for arbitrary hostile workloads. Scope checks do not
prove ownership. Multi-user authentication, tenant isolation, and production TLS
are absent; audit records are not tamper-proof evidence.

The in-memory backend simulates headers without networking. The
[header checks](assessments.md#header-checks) provide limited value checks, not
proof of security or complete CSP validation.

## Cleanup and failure

Resources have persisted names and assessment/attempt labels. Cleanup verifies
ownership, records observed IDs before removal, and uses successful enumeration
to verify absence. Creation intent is durable before Docker runs. An absent
resource whose creation is uncertain and ID unknown remains pending indefinitely;
an identified, removed resource can be verified. Elapsed time is not evidence.
Errors, permission failures, timeouts, and ownership mismatches never certify
cleanup; mismatched resources remain untouched.

Post-execution cancellation requires verified cleanup. Otherwise the assessment
fails with `cleanup_verified: false` and `cleanup_pending: true`.
[Reconciliation](architecture.md#recovery) revisits cleanup without rerunning failed
assessments; investigate unknown outcomes even after execution stops.

Inspect exact labels/names and API logs:

```bash
docker ps -a --filter label=seireth.assessment=ASSESSMENT_ID
docker network ls --filter label=seireth.assessment=ASSESSMENT_ID
docker compose logs api
```

Every attempt requires a journal. Missing/corrupt journals cannot certify cleanup
or authorize retries. Inspect journal and daemon activity before resolving
uncertainty; never clear flags merely because resources are absent, or use global
Docker prune on a shared daemon.

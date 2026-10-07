# Security model

SEIRETH is a local, single-operator development tool for owned or explicitly
authorized images. The fixed development actor provides no production
authentication. Example API/database bindings use loopback; a non-loopback API
binding exposes an unauthenticated service. Keep it off untrusted networks.
Report vulnerabilities through [SECURITY.md](../SECURITY.md).

## Enforced boundaries

Reads enforce project authorization. Browser writes reject cross-origin and
opaque `Origin` headers; CLI requests without `Origin` remain supported. Vite
preserves the browser's `Origin` and `Host` headers for these checks.

The GUI renders stored content as text. Target HTTP requests remain inside the
sandbox; the browser sends assessment requests only to Seireth.

Admission, execution, and retries check project/target ownership, origin/path,
plugins, and local image availability. Registered root URLs include child paths; traversal,
credentials, fragments, and ambiguous multiply encoded paths are rejected.
Redirect responses are inspected without following them. The runner reads
status and headers, then closes the response without reading or retaining its
body. Header-check applicability uses declared metadata; skipped or inconclusive
checks do not establish protection for an unassessed representation or destination.

The runner replaces the registered hostname with Docker alias `target`, measuring
the disposable image instance. HTTPS certificates must be valid and trusted for
that alias; custom hostname/TLS mapping is unsupported.

Targets and runners have an internal network, no published ports or Docker socket,
a non-root numeric user, dropped capabilities, no-new-privileges, read-only
filesystems, and CPU/memory/PID limits. Execution timeouts and cancellation interrupt
runner operations; cleanup independently verifies each resource.

## Privileged and remaining boundaries

The API and demo images default to UID/GID 65532. `docker-up` gives the API the
mounted Docker socket's group as a supplementary group; it never changes socket
permissions. Application files remain root-owned. The API's Docker socket still
grants substantial host control. Image discovery is a convenience, not an
approval or trust check; the operator chooses images and builds or pulls explicitly. Tags are mutable; containers share
a kernel and are unsuitable for arbitrary hostile workloads. URL boundaries do not
prove ownership. Multi-user authentication, tenant isolation, and production TLS
are absent; audit records are not tamper-proof evidence.

The in-memory backend simulates HTTP 200 and HTML headers without networking. The
[header checks](assessments.md#header-checks) provide limited value checks, not
proof of security or complete CSP validation.
The passive [cookie checks](assessments.md#cookie-checks) inspect only response
attribute requirements, skip malformed fields, and do not infer cookie purpose
or validate login flows. Cookie values are not retained in findings/evidence or
included in validation diagnostics.

[Evidence retrieval](assessments.md#retrieve-evidence) checks project authorization
before reading evidence. Invalid stored payloads fail the entire request;
diagnostics contain assessment/evidence IDs, never payloads or validation details.

## Cleanup and failure

Resources have persisted names and assessment/attempt labels. Cleanup verifies
ownership, records observed IDs before removal, and uses successful enumeration
to verify absence. Creation intent is durable before Docker runs. An absent
resource whose creation is uncertain and ID unknown remains pending indefinitely;
an identified, removed resource can be verified. Elapsed time is not evidence.
Inspection/enumeration failures, timeouts, and ownership or identity mismatches
leave cleanup unverified; mismatched resources remain untouched. A removal
command's exit status alone is inconclusive: verified absence and the journal's
creation state determine success.

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

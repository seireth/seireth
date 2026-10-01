# Assessments

Use `/docs` on your API for schemas and interactive requests, or run the
[verification workflow](getting-started.md#simulated-assessment).

## Authorize and select

| Step | Endpoint |
| --- | --- |
| Create project | `POST /api/v1/projects` |
| Register allowlisted target | `POST /api/v1/targets` |
| Authorize URL and expiry | `POST /api/v1/authorization-scopes` |
| Read plugin catalog | `GET /api/v1/plugins` |
| Submit assessment | `POST /api/v1/assessments` |

Scopes must match the project/target and registered origin/path, and remain
unexpired at creation, submission, execution, and retry. Requests use one
development actor; there is no login flow.

Get selectable plugin IDs from `GET /api/v1/plugins`. The catalog lists reviewed
built-ins with stable `id`, `name`, and `description`. Submit an explicit, nonnull,
nonempty selection of unique active IDs. See [Plugin development](plugins.md) to add checks.

The built-ins are `security-headers` and `cookie-security`. Select either or both,
for example `"plugins": ["security-headers", "cookie-security"]`. Registering a
plugin never automatically selects it; existing requests remain explicit.

Submit this body, replacing placeholder IDs with those returned above:

```json
{
  "project_id": "project-id",
  "target_id": "target-id",
  "scope_id": "scope-id",
  "plugins": ["security-headers"]
}
```

## Poll status and results

Submission returns HTTP 202 and a `Location` to poll. Selected IDs are persisted;
submission and `GET /api/v1/assessments/{id}` share this representation:

```json
{"id": "assessment-id", "status": "queued", "plugins": ["security-headers"], "result": null, "cleanup_pending": false}
```

`result` is null until an outcome exists. Background execution can advance the
initial status before the response arrives; handle every state.

| Status | Meaning |
| --- | --- |
| `queued` | Accepted; no execution outcome yet |
| `running` | Claimed and committed before sandbox execution |
| `cancelling` | Stopping execution; cleanup pending |
| `recovering` | Reconciling interruption before a possible retry |
| `completed` | Execution and cleanup succeeded |
| `failed` | Execution or cleanup failed; inspect result/logs |
| `cancelled` | Cancellation recorded; execution may never have started |

Poll until `completed`, `failed`, or `cancelled`. Append `/results` to `Location`
for findings. Example successful response with one finding (illustrative IDs/time):

```json
{
  "assessment_id": "assessment-id",
  "status": "completed",
  "cleanup_pending": false,
  "result": {
    "plugins": [{"id": "security-headers", "finding_count": 1}],
    "finding_count": 1,
    "sandbox_backend": "docker",
    "cleanup_verified": true,
    "cleanup_reason": null,
    "completed_at": "2026-09-25T12:00:00+00:00",
    "attempt": 1
  },
  "findings": [{
    "id": "finding-id",
    "plugin": "security-headers",
    "title": "Missing Content-Security-Policy",
    "severity": "medium",
    "description": "The response has no nonblank enforced Content-Security-Policy header.",
    "remediation": "Define and test an enforced Content-Security-Policy appropriate for this application."
  }]
}
```

`result.plugins` preserves selection order with per-plugin counts; `finding_count`
is the total. Zero findings does not establish security. Older findings may have
null remediation.

Execution errors populate `result.error`. Inspect cleanup independently:
unverified cleanup produces `failed`, even after cancellation. Both responses
include `cleanup_pending`; `result.cleanup_reason` explains uncertainty. Follow the
[cleanup procedure](security-model.md#cleanup-and-failure); reconciliation can
update cleanup fields after execution becomes terminal.

## Header checks

| Check | Accepted values |
| --- | --- |
| MIME type protection | `X-Content-Type-Options: nosniff` |
| Content security policy | A nonblank enforced `Content-Security-Policy` |
| Framing protection | `X-Frame-Options: DENY` / `SAMEORIGIN`, or an enforced CSP whose first `frame-ancestors` directive uses `'none'` alone or only supported sources, e.g. `'self' https://trusted.test` |

Bare `*`, scheme-only sources, and report-only framing policies do not qualify.
See the [implementation](../app/plugins/security_headers.py) for exact matching.
These checks do not fully validate CSP, prove security, or assess every response.

## Cookie checks

`cookie-security` analyzes every separate `Set-Cookie` field on the single assessed
response. It emits low-severity configuration findings, not exploit claims:

| Check | Reported configuration |
| --- | --- |
| SameSite compatibility | `SameSite=None` without `Secure` |
| `__Secure-` prefix | Missing `Secure` or an HTTP response URL |
| `__Host-` prefix | Missing `Secure`, HTTP, a nonempty `Domain`, or missing explicit `Path=/` |

Each field can produce one finding per violated rule; failed requirements for a
prefix are combined. Attribute names, SameSite values, and prefix matching are
case-insensitive; findings preserve the original cookie name. Repeated cookie
names are inspected separately. The parser retains only `Secure`, `SameSite`,
`Domain`, and `Path`. It ignores attribute values longer than 1,024 bytes after
trimming spaces and tabs; an ignored duplicate never replaces an earlier accepted
value. `Secure` counts by presence after this length check, and the last retained
value wins for the other attributes. Other attributes are discarded. Malformed
fields are skipped without failing the run, including malformed content in
discarded attributes.

Findings identify cookie names and explain remediation. Stored evidence contains
only names, rule IDs, the response URL, and normalized requirement values or
booleans. Cookie values and complete fields are excluded from findings, evidence,
and diagnostics. Evidence is not exposed by the current results endpoint.

There are no general warnings for absent `Secure`, `HttpOnly`, or explicit
`SameSite`, and no login, replay, cookie-jar, newer-prefix, or full browser-policy
validation. Zero findings does not establish cookie security. The owned demo's
`/cookies` path emits four fields: one ordinary cookie and three violations.
Selecting both plugins there produces six findings (three per plugin).

## Cancellation and audit

`POST /api/v1/assessments/{id}/cancel` returns `id` and `status`:
queued work cancels immediately (200; its assessment result may remain null);
active work returns 202 / `cancelling`. Pending repeats are idempotent; terminal
runs return 409. Continue polling nonterminal states, including recovery.

Cancellation interrupts the runner and verifies cleanup before `cancelled`.
Deadline/scope expiry fails after cleanup. [Crash recovery](architecture.md#recovery)
can retry once after cleanup and fresh authorization; results expose `attempt`.

`GET /api/v1/projects/{id}/audit-events` returns chronological events. Normal success
records `project.created`, `target.registered`, `scope.authorized`,
`assessment.queued`, `assessment.running`, and `assessment.completed`.
Cancellation/recovery add their transitions, including `assessment.cancelling`.
Each transition commits with its audit record.

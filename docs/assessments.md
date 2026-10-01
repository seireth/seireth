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

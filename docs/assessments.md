# Assessments

Open `/docs` on your configured API address for request schemas and interactive
requests. `python -m app verify` runs the full example and checks findings, cleanup,
and audit ordering; its implementation is in [app/verify.py](../app/verify.py).

| Operation | Endpoint |
| --- | --- |
| Create a project | `POST /api/v1/projects` |
| Register an allowlisted target | `POST /api/v1/targets` |
| Authorize a bounded URL and expiry | `POST /api/v1/authorization-scopes` |
| Submit an assessment using those IDs | `POST /api/v1/assessments` |
| Read audit events | `GET /api/v1/projects/{id}/audit-events` |

## Authorization

A scope must belong to the same project and target, be unexpired when created
and when an assessment is submitted, executed, or retried, and stay within the registered URL's
origin and path. The only supported profile is `passive`. All requests currently
use one development actor; there is no user authentication flow.

## Status and result

Creation returns `202 Accepted`. Poll the `Location` response header, appending
`/results` for findings, until `completed`, `failed`, or `cancelled`. A queued record is:

```json
{"id": "assessment-id", "status": "queued", "result": null, "cleanup_pending": false}
```

`result` is nullable because creation acknowledges background work before an
outcome exists. The same assessment representation is returned by
`GET /api/v1/assessments/{id}`. Initial status can race with background execution;
clients should handle any returned state.

| Status | Meaning |
| --- | --- |
| `queued` | Work accepted, no recorded execution outcome yet |
| `running` | Claimed and committed before sandbox execution |
| `cancelling` | Cancellation requested; execution is stopping and cleanup is pending |
| `recovering` | Interrupted attempt being reconciled before a possible retry |
| `completed` | Execution succeeded and cleanup reported success |
| `failed` | Execution or cleanup failed; inspect `result` and server logs |
| `cancelled` | Cancellation recorded; execution may not have started |

`GET /api/v1/assessments/{id}/results` returns `assessment_id`, `status`, `result`,
and a `findings` array. A successful result contains `plugin`, `finding_count`,
`sandbox_backend`, `cleanup_verified`, `completed_at`, and the attempt number. A zero count means
the plugin found no missing required headers, not that the target is secure.

Execution failures include an `error` in the result. Unverified cleanup always
produces `failed`, including after cancellation. Assessment and results responses
include `cleanup_pending`; `result.cleanup_reason` explains unresolved cleanup.
Inspect `cleanup_verified` independently of execution success. See the
[cleanup procedure](security-model.md#cleanup-and-failure) for reconciliation,
resource inspection, and why absence alone cannot resolve uncertain creation.

## Cancellation and audit events

`POST /api/v1/assessments/{id}/cancel` immediately cancels queued work (HTTP 200,
possibly null result). For active work it returns HTTP 202 and `cancelling`;
repeated pending requests are idempotent. Terminal runs return HTTP 409.
Continue polling during `running`, `cancelling`, and `recovering`.

Cancellation interrupts the runner and cleans up before the final `cancelled`
outcome. Deadline or scope expiry produces `failed` after cleanup. Crash recovery
can retry once after cleanup and fresh policy validation; results expose `attempt`.

Audit events include `assessment.running`, `assessment.cancelling`, and recovery
transitions as applicable. A normal success records project creation, target
registration, scope authorization, assessment queuing, running, and completion.
Transitions and their audit records are committed together.

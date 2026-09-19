# Assessments

The API explorer at `http://127.0.0.1:8000/docs` contains the generated request
schemas. For an executable end-to-end example, use the following in an activated
environment while the API is running:

```python
from datetime import datetime, timedelta, timezone
import time
import httpx

with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
    def post(path, body):
        response = client.post(path, json=body)
        response.raise_for_status()
        return response

    project = post("/api/v1/projects", {"name": "Example"}).json()
    target = post("/api/v1/targets", {
        "project_id": project["id"], "name": "Demo",
        "url": "http://demo-target:8080",
    }).json()
    scope = post("/api/v1/authorization-scopes", {
        "project_id": project["id"], "target_id": target["id"],
        "allowed_url": "http://demo-target:8080",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
    }).json()
    accepted = post("/api/v1/assessments", {
        "project_id": project["id"], "target_id": target["id"],
        "scope_id": scope["id"], "profile": "passive",
    })
    location = accepted.headers["Location"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = client.get(location + "/results")
        response.raise_for_status()
        report = response.json()
        if report["status"] in {"completed", "failed", "cancelled"}:
            print(report)
            break
        time.sleep(0.2)
    else:
        raise TimeoutError(f"Still waiting for {location}; inspect or cancel it")
```

For automated verification, `python -m app verify` additionally asserts successful
completion, demo findings, cleanup, and audit ordering.

## Authorization

A scope must belong to the same project and target, be unexpired when created
and when an assessment is submitted, executed, or retried, and stay within the registered URL's
origin and path. The only supported profile is `passive`. All requests currently
use one development actor; there is no user authentication flow.

## Status and result

Creation returns `202 Accepted`, with a queued record initially shaped like this:

```json
{"id": "assessment-id", "status": "queued", "result": null}
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

An execution failure can produce:

```json
{
  "sandbox_backend": "docker",
  "cleanup_verified": true,
  "error": "assessment execution failed",
  "completed_at": "2026-09-17T12:00:00+00:00"
}
```

Unverified cleanup always produces `failed`, including after cancellation. Inspect
`result.cleanup_verified` independently of whether execution itself succeeded.

Assessment and results responses also include `cleanup_pending`. The nullable
`result.cleanup_reason` explains why cleanup remains unresolved. Docker creation
intent is committed before each command; a timeout or missing response can leave
creation uncertain even when no resource is currently visible. Such assessments
remain failed and pending while other assessments continue.

The dispatcher checks failed pending cleanup every 30 seconds and at startup.
When a late resource appears, it verifies ownership, records its ID, removes it,
and verifies absence. Successful reconciliation clears `cleanup_pending` and
`cleanup_reason`, sets `cleanup_verified`, and records one
`assessment.cleanup_verified` event. It preserves the original error and does not
rerun the failed assessment. Elapsed time alone never resolves uncertainty.

For persistent uncertainty, inspect API logs, the attempt's `operation_journal`,
and Docker resources selected by both `seireth.assessment` and `seireth.attempt`
labels. Check daemon availability and whether a create request is still in flight.
Do not clear database flags merely because `docker ps` or `docker network ls` is
empty. Legacy unfinished Docker attempts have no operation history and are treated
conservatively; they can remain pending even after resources disappear. There is
no automatic timeout or administrative override that certifies those attempts.

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

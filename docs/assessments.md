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
and when an assessment is submitted, and stay within the registered URL's
origin and path. The only supported profile is `passive`. All requests currently
use one development actor; there is no user authentication flow.

## Status and result

Creation returns `202 Accepted`, normally with this shape:

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
| `running` | Execution state; intermediate updates may not be visible until the worker commits |
| `completed` | Execution succeeded and cleanup reported success |
| `failed` | Execution or cleanup failed; inspect `result` and server logs |
| `cancelled` | Cancellation recorded; execution may not have started |

`GET /api/v1/assessments/{id}/results` returns `assessment_id`, `status`, `result`,
and a `findings` array. A successful result contains `plugin`, `finding_count`,
`sandbox_backend`, `cleanup_verified`, and `completed_at`. A zero count means
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

Some worker failures have fewer fields. A cleanup failure can retain plugin
summary fields with `cleanup_verified: false` and status `failed`. Always inspect
status together with the result instead of assuming one fixed failure shape.

## Cancellation and audit events

`POST /api/v1/assessments/{id}/cancel` requests cancellation of queued or running
work. Already terminal assessments return `409`. Cancellation is cooperative;
it does not immediately terminate a Docker subprocess. Cancellation before
execution may leave `result` null. A cancelled status alone does not prove cleanup.

`GET /api/v1/projects/{project_id}/audit-events` returns chronological events.
A successful demo records project creation, target registration, scope
authorization, assessment queuing, and assessment completion.

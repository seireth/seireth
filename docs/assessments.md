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
{
  "id": "assessment-id",
  "project_id": "project-id",
  "target_id": "target-id",
  "scope_id": "scope-id",
  "created_at": "2026-10-02T12:00:00Z",
  "status": "queued",
  "plugins": ["security-headers"],
  "result": null,
  "cleanup_pending": false
}
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
is the total. Zero findings does not establish security.

Execution errors populate `result.error`. Inspect cleanup independently:
unverified cleanup produces `failed`, even after cancellation. Both responses
include `cleanup_pending`; `result.cleanup_reason` explains uncertainty. Follow the
[cleanup procedure](security-model.md#cleanup-and-failure); reconciliation can
update cleanup fields after execution becomes terminal.

The GUI polls every second during execution and every five seconds while terminal
cleanup remains pending, then stops. Refocus refreshes data; leaving the page
cancels its reads. Evidence failures show a retry action without hiding findings.

## Retrieve evidence

`GET /api/v1/assessments/{assessment_id}/evidence` returns `assessment_id`,
`status`, `cleanup_pending`, and an `evidence` array ordered by evidence ID.
Match each entry's `finding_id` to the finding's `id` in the results response.

```json
{
  "assessment_id": "assessment-id",
  "status": "completed",
  "cleanup_pending": false,
  "evidence": [{
    "id": "evidence-id",
    "finding_id": "finding-id",
    "kind": "http-response",
    "data": {
      "url": "http://demo-target:8080/",
      "header": "content-security-policy"
    }
  }]
}
```

| Evidence payload | Public fields |
| --- | --- |
| Security header | `url`, `header` (`x-content-type-options`, `content-security-policy`, or `x-frame-options`) |
| SameSite cookie | `url`, `header="set-cookie"`, `cookie_name`, `rule="samesite-none-without-secure"`, `samesite="none"`, `secure` |
| Secure prefix cookie | `url`, `header="set-cookie"`, `cookie_name`, `rule="secure-prefix"`, `secure`, `https` |
| Host prefix cookie | `url`, `header="set-cookie"`, `cookie_name`, `rule="host-prefix"`, `secure`, `https`, `domain_present`, `root_path` |

All listed fields are required; URLs must use HTTP(S), cookie names preserve their
spelling, and booleans must be JSON `true` or `false`. Cookie values and complete
header fields are never returned; unlisted fields are rejected.
Invalid stored evidence causes HTTP 500 with `stored evidence is invalid`;
the entire response fails. See [diagnostic redaction](security-model.md).

Access uses the same project authorization as results: unknown assessments
return 404 and denied project access returns 403. Expired scopes still allow reads.
The array is empty unless the assessment is completed with findings.
Retrieval runs no assessment and writes no database records or audit events.

## Discover saved records

| Read endpoint | Response |
| --- | --- |
| `GET /api/v1/projects` | Current operator's projects |
| `GET /api/v1/projects/{id}` | Project name and creation time |
| `GET /api/v1/projects/{id}/targets` | Registered targets |
| `GET /api/v1/targets/{id}` | Target name, image, URL, and project ID |
| `GET /api/v1/projects/{id}/authorization-scopes` | Scopes, including expired scopes; optional `target_id` from the same project |
| `GET /api/v1/authorization-scopes/{id}` | Scope project/target IDs, URL boundary, and expiry |
| `GET /api/v1/projects/{id}/assessments` | Assessment history |
| `GET /api/v1/runtime` | `sandbox_backend`, `default_target_image`, `allowed_target_images` |

Project, target, scope, and assessment lists return `items` and `has_more`.
Use `offset` (default 0) and `limit` (default 50, range 1–100). While `has_more` is
true, advance `offset` by `limit`. Projects and assessments sort newest first,
scopes by expiry descending, and targets by ID, with ID tie breakers.
Audit events return a chronological array.

Unknown resources return 404; denied project access returns 403. Expired
scopes permit reads but cannot authorize execution. Reads perform no assessment
work and write no records or audit events.

Browser writes require a same-origin `Origin`; cross-origin and opaque origins
return 403. CLI requests without `Origin` continue to work.

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
and diagnostics. Retrieve evidence separately using the endpoint above.

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

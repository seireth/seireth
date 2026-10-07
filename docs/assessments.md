# Assessments

Use the API's generated `/docs` explorer for schemas and interactive requests, or
run the [verification workflow](getting-started.md#simulated-assessment).

## Register and select

| Step | Endpoint |
| --- | --- |
| Create project | `POST /api/v1/projects` |
| Register image and base URL | `POST /api/v1/targets` |
| Discover local tagged images | `GET /api/v1/target-images` |
| Read plugin catalog | `GET /api/v1/plugins` |
| Submit assessment | `POST /api/v1/assessments` |

Register a target with `project_id`, `name`, `image`, and `url`. Image discovery
returns `{"items":[{"image":"repository:tag","id":"sha256:…"}]}` and is optional.
Docker rejects missing local images with HTTP 400 and daemon failures with 503.
The simulated backend accepts valid image metadata without Docker.

Assessment URLs must stay within the target's origin and registered path, including
child paths. Ownership, URL boundaries, plugins, and local image availability are
rechecked during submission, execution, and recovery retries. Requests use one
development actor; there is no login flow.

Get selectable IDs from `GET /api/v1/plugins`. The built-ins are `http-security-headers`
and `cookie-security`; select either or both. Selection must be explicit, nonempty,
and contain unique active IDs. Registering a plugin never automatically selects it.
See [Plugin development](plugins.md) to add checks.

Submit this body, replacing placeholder IDs with those returned above:

```json
{
  "project_id": "project-id",
  "target_id": "target-id",
  "url": "http://demo-app:8080/cookies",
  "plugins": ["http-security-headers"]
}
```

## Poll status and results

Submission returns HTTP 202, the saved assessment, and a `Location` to poll.
The requested URL and selected plugin IDs are persisted and returned in assessment details and history. `result` is null until an outcome exists;
execution can advance the initial status before the response arrives.

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
for findings. For completed assessments, `result` includes `sandbox_backend`,
`attempt`, and `completed_at`. `result.plugins` preserves selection order with
per-plugin counts; `result.finding_count` is the total. `result.response` contains
the HTTP `status_code` and normalized `media_type` (null when unknown). The
`http-security-headers` entry includes `checks`, each with a stable `rule_id`,
`status`, and short `reason`. Only `failed` checks generate findings. `passed`
means the limited rule accepted the response; `skipped` means the rule did not
apply; `inconclusive` means document applicability could not be established.
The dashboard shows these outcomes and response context even with zero findings.
Zero findings does not establish security.

Execution errors populate `result.error`. Inspect cleanup independently:
unverified cleanup produces `failed`, even after cancellation. Both responses
include `cleanup_pending`; `result.cleanup_verified` records verification and
`result.cleanup_reason` explains uncertainty. Follow the
[cleanup procedure](security-model.md#cleanup-and-failure); reconciliation can
update cleanup fields after execution becomes terminal.

The GUI polls every second during execution and every five seconds while terminal
cleanup remains pending, then stops. Refocus refreshes data; leaving the page
cancels its reads. Evidence failures show a retry action without hiding findings.

## Retrieve evidence

`GET /api/v1/assessments/{assessment_id}/evidence` returns an `evidence` array ordered
by evidence ID. Match each entry's `finding_id` to a finding's `id` in `/results`.
The array is empty unless the assessment is completed with findings.

Header evidence identifies the response URL, header, stable `rule_id`, HTTP
`status_code`, normalized `media_type`, safe observed `condition` (missing,
blank, unrecognized, or unrestricted), and expected requirement. Raw CSP policies
and arbitrary header values are excluded. Cookie evidence identifies
the cookie name, rule, and normalized requirement values or flags. Cookie values
and complete fields are excluded. See `/docs` for the accepted payload models;
unlisted fields are rejected. Invalid stored evidence fails the entire response
with HTTP 500 and `stored evidence is invalid`. See
[diagnostic redaction](security-model.md).

## Discover saved records

| Read endpoint | Response |
| --- | --- |
| `GET /api/v1/projects` | Current operator's projects |
| `GET /api/v1/projects/{id}` | Project name and creation time |
| `GET /api/v1/projects/{id}/targets` | Registered targets |
| `GET /api/v1/targets/{id}` | Target name, image, URL, and project ID |
| `GET /api/v1/projects/{id}/assessments` | Assessment history |
| `GET /api/v1/runtime` | `sandbox_backend` |

Project, target, and assessment lists return `items` and `has_more`.
Use `offset` (default 0) and `limit` (default 50, range 1â€“100). While `has_more` is
true, advance `offset` by `limit`. Projects and assessments sort newest first,
and targets by ID, with ID tie breakers.
Audit events return a chronological array.

Unknown resources return 404; denied project access returns 403. Reads perform no assessment
work and write no records or audit events.

Browser writes require a same-origin `Origin`; cross-origin and opaque origins
return 403. CLI requests without `Origin` continue to work.

## Header checks

Select `http-security-headers` (**HTTP security headers** in the catalog).
The former `security-headers` ID is rejected. Applicability is based on declared
status and content type, without inspecting a body or assessing redirect
destinations. Content types are normalized by case and stripped of parameters;
repeated declarations must agree and be well formed.

| Response | Applicable checks |
| --- | --- |
| HTML or XHTML, including rendered error pages | All three |
| JSON (including `application/*+json`), JavaScript, CSS, plain text, or recognized raster images | `nosniff`; CSP and framing are skipped |
| 301, 302, 303, 307, 308 | All skipped; destination not assessed |
| Informational status, 204, 205, 304 | All skipped; no complete representation assessed |
| Missing, malformed, conflicting, or unsupported content type | `nosniff`; CSP and framing are inconclusive |

The status rules take precedence over content type. Unsupported types include
PDF and SVG. Declared metadata may not describe the actual body; these outcomes
do not establish how a browser would render it. The document rules follow
[OWASP's framing and CSP applicability guidance](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html).

| Stable rule ID | Accepted protection |
| --- | --- |
| `x-content-type-options` | `X-Content-Type-Options: nosniff` |
| `content-security-policy` | A nonblank enforced `Content-Security-Policy` |
| `framing-protection` | `X-Frame-Options: DENY` / `SAMEORIGIN`, or an enforced CSP whose first `frame-ancestors` directive uses `'none'` alone or only supported sources, e.g. `'self' https://trusted.test` |

Bare `*`, scheme-only sources, and report-only framing policies do not qualify.
The MIME check uses the first parsed header-list value. Any enforced
`frame-ancestors` directive overrides `X-Frame-Options`; one restrictive enforced
policy is enough, and an empty ancestor list also counts as blocking framing.
When no such directive exists, the plugin uses `X-Frame-Options`, including
repeated/comma-separated values and conflicts that block framing.
See the [implementation](../app/plugins/http_security_headers.py) for exact matching.
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
Execution timeout fails after cleanup. [Crash recovery](architecture.md#recovery)
can retry once after cleanup and fresh boundary and image checks; results expose `attempt`.

`GET /api/v1/projects/{id}/audit-events` returns chronological events. Normal success
records `project.created`, `target.registered`,
`assessment.queued`, `assessment.running`, and `assessment.completed`.
Cancellation/recovery add their transitions, including `assessment.cancelling`.
Each transition commits with its audit record.

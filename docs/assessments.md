# Assessments

For Docker bundles, existing websites, authentication, route plans, release
checks, and reports, use [Docker and website workflows](workflows.md).
The single-URL submission below is normalized into the same execution plan.
Use the API's `/docs` explorer or the [verification workflow](getting-started.md#real-docker-assessment).

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

Assessment URLs must stay within the target's origin and registered path, including
child paths. Ownership, URL boundaries, plugins, and local image availability are
rechecked during submission, execution, and recovery retries. Requests use one
development actor; there is no login flow.

Get selectable IDs from `GET /api/v1/plugins`. The built-ins are `http-security-headers`,
`cookie-security`, and `csp-policy`; select any combination. Selection must be explicit, nonempty,
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
The frozen plan persists request and plugin configuration; URL and plugin summaries are derived from it and returned in assessment details and history. `result` is null until an outcome exists;
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
`attempt`, and `completed_at`. Each entry of `result.routes` preserves selected
plugins and their counts; `result.finding_count` is the published total. Each route response contains
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

New execution attempts persist `result.execution`: UTC `started_at` and
`deadline_at`, the registered target snapshot, and the ordered plugin IDs and
versions. This metadata is committed before sandbox resources are created and is
retained for failed runs as well as completed runs. `result.error_kind` separates
`plugin_error`, `timeout`, and other `execution_error` outcomes; plugin failures
also identify `failed_plugin`. Failed or cancelled batches may publish clearly
labelled results from completed routes only after verified cleanup; incomplete
routes publish no findings. Such batches never pass the release gate.

The GUI refreshes execution and pending cleanup automatically. Evidence failures
offer a retry without hiding findings.

## Retrieve evidence

`GET /api/v1/assessments/{assessment_id}/evidence` returns an `evidence` array ordered
by evidence ID. Match each entry's `finding_id` to a finding's `id` in `/results`.
The array contains evidence for published findings from the terminal attempt.
Cleanup must be verified before any findings or evidence are released.

Header evidence identifies the response URL, header, stable `rule_id`, HTTP
`status_code`, normalized `media_type`, safe observed `condition` (missing,
blank, unrecognized, or unrestricted), and expected requirement. Raw CSP policies
and arbitrary header values are excluded. The rule, header, condition, and
requirement must be consistent; `unrestricted` applies only to framing evidence
backed by CSP. Cookie evidence identifies
the cookie name, rule, and normalized requirement values or flags. Cookie values
and complete fields are excluded. See `/docs` for the accepted payload models;
unlisted fields are rejected. Invalid stored evidence fails the entire response
with HTTP 500 and `stored evidence is invalid`. See
[diagnostic redaction](security-model.md).

## Download assessment reports

`GET /api/v1/assessments/{assessment_id}/report` returns a versioned JSON snapshot
for a `completed`, `failed`, or `cancelled` assessment. Other states return 409
after project authorization. The dashboard's **Download JSON** and **Download HTML**
buttons each fetch a fresh snapshot; HTML generation happens in the browser.

The report uses `schema_version: 1` and includes the project, frozen plan/target,
execution metadata, route outcomes, coverage, cleanup, verdict, comparison,
findings, and evidence. Response facts and plugin checks live under
`assessment.result.routes`; findings link to their route and evidence by ID.

Exports read persisted data without rerunning checks, so restarts or plugin/target
changes do not rewrite what ran. `generated_at` records the export time; cleanup
fields reflect reconciliation and may still be pending. JSON retains saved
ISO 8601 timestamps; HTML displays them in UTC. Invalid stored timestamps fail
validation.

See [Contributing](../CONTRIBUTING.md#tests) for real Docker lifecycle and report
durability tests.

HTML includes expanded finding evidence and inline styles, works offline, and can
be printed using the browser. It contains no scripts or external assets. Stored
text is rendered as text. Both formats retain the existing evidence validation
and redaction rules: raw cookie values, complete fields, and arbitrary header
values are excluded. Invalid evidence or documented result fields fail the entire
export with HTTP 500 and generic diagnostics. Authorized URLs, names, and finding
text are preserved; reports do not anonymize target details.

## Discover saved records

| Read endpoint | Response |
| --- | --- |
| `GET /api/v1/projects` | Current operator's projects |
| `GET /api/v1/projects/{id}` | Project name and creation time |
| `GET /api/v1/projects/{id}/targets` | Registered targets |
| `GET /api/v1/targets/{id}` | Target name, image, URL, and project ID |
| `GET /api/v1/projects/{id}/assessments` | Assessment history |

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
Applicability is based on declared
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

## CSP policy checks

Select `csp-policy` (**CSP policy** in the catalog) independently or alongside the
baseline header checks. It analyzes the same fetched response without additional
requests. A nonblank header can pass the baseline presence check while the CSP
policy plugin identifies overly broad script permissions.

| Rule | Covered permission | Severity |
| --- | --- | --- |
| `csp-script-sources` | Arbitrary HTTP(S) origins for parser-inserted scripts without nonce/integrity authorization | Medium |
| `csp-inline-scripts` | Arbitrary inline script elements or inline event handlers | Medium |
| `csp-eval` | Unrestricted JavaScript string evaluation | Low |

For example, `script-src https: 'unsafe-inline' 'unsafe-eval'; frame-ancestors 'none'`
passes CSP presence and framing, but fails all three policy checks. A policy using
`script-src 'self'` has no covered policy finding; that does not certify its
allowlist or application as secure.

The plugin applies the same document-response eligibility as baseline CSP checks,
including HTML error pages. Missing or blank enforced CSP yields three skipped
checks; report-only headers do not enforce protection. Multiple policies combine
restrictively. Fallbacks, first duplicate directives, syntactic nonces/hashes,
`strict-dynamic`, and a script-blocking CSP sandbox are accounted for. Nonce
recognition does not measure randomness, reuse, or correspondence with document
elements. Nonces alone do not suppress broad network sources.

Network-source coverage recognizes `*`, `http:`, `https:`, and global HTTP(S)
wildcard hosts without path or port constraints. Specific hosts are outside the
broad-source finding. Unsupported permissions such as `data:`, `blob:`, constrained
global wildcards, and relevant Trusted Types interactions remain inconclusive
when no supported restriction or permission settles the covered capability.
`wasm-unsafe-eval` does not permit JavaScript string evaluation.

Trusted Types requirements and evaluation keyword interactions are assessed across
the enforced policy set. When enabled, `trusted-types-eval` keeps evaluation
inconclusive even with other source-list restrictions; a script-blocking sandbox
remains conclusive. Directives containing non-ASCII text are discarded as browsers
discard them, while still counting toward the analysis limits.

Analysis is limited to 64 KiB of UTF-8 CSP text, 32 fields, 32 nonblank policies,
128 directives per policy, and 256 source tokens per directive. Duplicate and
ignored directives count toward limits. Exceeding any limit returns three
inconclusive checks and no findings; partial input never certifies a policy.

CSP evidence uses the existing `http-response` kind. It contains the response URL,
status, document media type, `header: "content-security-policy"`, rule ID,
`policy_count`, and `observations`. Each observation identifies its one-based
`policy_index`, `context` (`network-script`, `inline-script`, `script-attribute`,
or `eval`), effective `directive` (or null), and a closed `condition`:
`missing-directive`, `wildcard-source`, `http-scheme-source`,
`https-scheme-source`, `global-host-source`, `unsafe-inline`, or `unsafe-eval`.
Every reported context has complete policy coverage. Raw policies, nonces, hashes,
allowlist hostnames, and report destinations are excluded.

Findings describe header permissions. Response bodies and meta-delivered CSP are
not inspected, and findings do not establish exploitable XSS. Browser probes test
the supported semantics independently of analyzer expectations. See the
[CSP3 algorithms](https://www.w3.org/TR/2026/WD-CSP3-20260916/) and
[script-src reference](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/script-src).

## Cookie checks

`cookie-security` inspects separate `Set-Cookie` fields. Prefix and SameSite
findings have low severity; declared session-cookie findings have medium severity:

| Check | Reported configuration |
| --- | --- |
| SameSite compatibility | `SameSite=None` without `Secure` |
| `__Secure-` prefix | Missing `Secure` or an HTTP response URL |
| `__Host-` prefix | Missing `Secure`, HTTP, a nonempty `Domain`, or missing explicit `Path=/` |

Each field can produce one finding per violated rule; prefix failures are combined.
Attribute names, SameSite values, and prefixes are case-insensitive; cookie names
are preserved and repeated fields inspected separately. The parser retains
`Secure`, `HttpOnly`, `SameSite`, `Domain`, and `Path`, ignoring attribute values
over 1,024 bytes. Flags count by presence; other attributes use the last retained
value. Malformed fields are skipped.

Findings identify cookie names and explain remediation. Stored evidence contains
only names, rule IDs, the response URL, and normalized requirement values or
booleans. Cookie values and complete fields are excluded from findings, evidence,
and diagnostics. Retrieve evidence separately using the endpoint above.

Declared `session_cookies` also require `Secure` and `HttpOnly`; use
`expected_cookies` when absence must block coverage. Unrelated cookies receive
no general warnings for missing flags. Login, replay, cookie-jar, newer-prefix,
and full browser-policy validation are outside these checks. The owned demo's
`/cookies` path emits four fields: one ordinary cookie and three violations.
Selecting both plugins there produces six findings (three per plugin).

## Cancellation and audit

`POST /api/v1/assessments/{id}/cancel` returns `id` and `status`:
queued work cancels immediately (200 with a terminal result);
active work returns 202 / `cancelling`. Pending repeats are idempotent; terminal
runs return 409. Continue polling nonterminal states, including recovery.

Cancellation interrupts the runner and verifies cleanup before `cancelled`.
Execution timeout fails after cleanup. [Docker crash recovery](architecture.md#recovery)
can retry once after cleanup and fresh boundary and image checks; results expose `attempt`.

`GET /api/v1/projects/{id}/audit-events` returns chronological events. Normal success
records `project.created`, `target.registered`,
`assessment.queued`, `assessment.running`, and `assessment.completed`.
Cancellation/recovery add their transitions, including `assessment.cancelling`.
Each transition commits with its audit record.

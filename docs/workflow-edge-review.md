# Workflow edge review — 2026-10-15

Reviewed `feat/unified-assessment-workflows` from commit
`73eb6cc382667bb8075e84451ea564ff0332172f`, fetched from origin before editing.
The review covered application modules and their functions, dashboard workflows,
test responsibilities, packaging, and CI configuration. Validation used disposable
PostgreSQL databases and synthetic local websites and Docker images.

## Confirmed defects and changes

| Defect | Resulting behavior | Regression coverage |
| --- | --- | --- |
| Mount validation inspected the original spelling of paths. `/./proc`, `//proc/self`, and root aliases passed; tmpfs also accepted delimiters and control characters. | One Pydantic `ContainerPath` type normalizes both volume and tmpfs paths and rejects protected destinations and ambiguous options. | Both mount types exercise traversal, root/kernel aliases, delimiters, NUL, and newline input. |
| Failure to persist unattempted routes escaped finalization even after HTTP sockets closed. | The worker retains cleanup proof, acknowledges HTTP closure, and records a failed, blocked assessment with incomplete coverage. | A real website request followed by persistent route-write failures must finish without publishing findings or replaying requests. |
| The new-assessment component retained target, route, and registration state when its project parameter changed. | A form keyed by project resets all project-scoped draft and mutation state. | Navigation between projects clears the target, URL, route plan, and registration draft and disables submission. |
| Missing or malformed operator configuration raised unhandled errors from target registration and the profile catalog. | Both endpoints return a sanitized HTTP 503 response. Registration produces no records or audit events. | Missing and malformed configuration are exercised through both endpoints with before/after database snapshots. |
| Container recovery acceptance used the removed `python -m app` entry point and assumed its config file was readable by UID 65532. | The test uses `app.cli.commands`, explicitly grants read access to its synthetic public config, and checks target-registration status. | The real packaged API restart test runs through migration, execution, process death, and recovery. |
| Cancellation acceptance could interrupt resource creation but always expected verified cancellation. Creation uncertainty correctly leaves cleanup pending, making the test intermittent. | The lifecycle test waits for the target's durable identity before requesting cancellation, as it already did for crash recovery. | Verified cancellation, crash recovery, and image-reference removal retain their strict lifecycle and cleanup assertions; uncertain-creation tests remain separate. |

The new regression suites reproduced each defect before its fix.

## File and function review decisions

Paths in this table are relative to `app/`.

| Files | Functions or responsibilities assessed; decision |
| --- | --- |
| `main.py` | Lifespan ownership, readiness, dashboard fallback, and asset traversal handling. Keep the current separation between API and frontend serving. |
| `api/assessments.py` | Admission, project ownership, baseline selection, publication, evidence validation, reports, and cancellation. Keep row-locked cancellation and publication gates. |
| `api/dependencies.py` | Project authorization, pagination, and browser-origin checks. Retain rejection before write side effects. |
| `api/projects.py` | Project creation, ordered/scoped reads, and audit retrieval. Retain shared authorization and pagination. |
| `api/targets.py`, `api/router.py` | Target registration, local images, plugin/profile catalogs. Handle unavailable operator configuration explicitly. |
| `api/schemas.py` | Input alternatives, URL/storage bounds, source kind, and public report/evidence contracts. Preserve validated response models. |
| `core/config.py`, `core/constraints.py`, `core/identity.py` | Finite execution limits, database selection, shared persisted-field limits, and the documented development actor. Keep centralized constraints. |
| `persistence/db.py`, `persistence/models.py` | Connection bounds, ownership records, route/finding/evidence links, and attempt constraints. Keep PostgreSQL authoritative. |
| `persistence/migrations/env.py`, `persistence/migrations/versions/0001_current_schema.py`, `persistence/migrations/script.py.mako` | Migration transactions, schema constraints, and packaging. Retain explicit migrations outside API startup. |
| `assessments/plans.py` | Frozen plans, required-check inference, pinned images, references, trust, and deadlines. Keep admission-time snapshots and strict stored-plan validation. |
| `assessments/profiles.py` | Header/environment validation, dependency ordering, secret resolution, grants, mounts, and sanitized catalogs. Share the mount-path validator between both mount types. |
| `assessments/policy.py` | Raw URL validation, origin/path boundaries, and public URL redaction. Keep the shared admission/execution boundary. |
| `assessments/http_fetch.py` | DNS pinning, connection authorization, TLS/SNI, header budgets, redirects, and response closure. Preserve per-connection checks and header-only requests. |
| `assessments/website.py` | Runtime credential resolution, cancellation, closure, and cleanup acknowledgment. Retain native HTTP execution without Docker. |
| `assessments/bundle.py` | Durable creation intent, resource identity, restrictions, dependency readiness, secret transport, subprocess reaping, and cleanup verification. Preserve independent cleanup and conservative uncertainty. |
| `assessments/runner.py`, `assessments/images.py` | Bounded runner protocol and local image inspection. Keep explicit image preparation and safe diagnostics. |
| `assessments/execution.py`, `assessments/processes.py` | Cancellation/deadlines, process lifetime, PID reuse, and container identity. Preserve conservative process-exit proof. |
| `assessments/worker.py` | Dispatcher ownership, claims, route transactions, recovery, and retries. Keep short transactions and ownership fencing. |
| `assessments/lifecycle.py`, `assessments/results.py` | Transitions, audit events, terminal results, and public result validation. Keep execution and cleanup outcomes separate. |
| `assessments/workflows.py` | Plugin isolation, route atomicity, publication, coverage, strict verdicts, and comparison. Preserve cleanup outcomes when placeholder writes fail. Retain bulk finding-count aggregation. |
| `plugins/base.py`, `plugins/registry.py` | Immutable analysis context, copied observations, plugin contracts, and approved selection. Keep independent plugin observations. |
| `plugins/http_security_headers.py`, `plugins/http_security_headers_contract.py`, `plugins/response_context.py` | Header parsing, browser applicability, framing, and value-free rule metadata. Retain explicit skipped/inconclusive outcomes. |
| `plugins/cookie_security.py` | Repeated cookies, prefixes, attributes, expected/session declarations, and redaction. Keep passive scope and value-free evidence. |
| `plugins/csp_policy.py`, `plugins/csp_policy_contract.py` | CSP parsing budgets, directive precedence, intersecting policies, inline contexts, and Trusted Types uncertainty. Retain browser-backed enforcement tests. |
| `plugins/evidence.py` | Closed evidence vocabulary, rule consistency, and complete policy coverage. Keep validation at persistence and retrieval boundaries. |
| `cli/assess.py`, `cli/commands.py`, `cli/verify.py` | Startup/migration gates, polling deadlines, report-first output, failure codes, and verification integrity. Retain behavior tests; remove simple mocked forwarding tests. |
| `dashboard/src/App.tsx`, `dashboard/src/main.tsx`, `dashboard/src/api/{client,queries,types}.ts` | Routing, relative API requests, errors, cancellation signals, pagination, caching, and typed contracts. Keep React Query as the shared data layer. |
| `dashboard/src/pages/{ProjectsPage,ProjectPage,NewAssessmentPage,AssessmentPage}.tsx` | Creation, scope changes, target selection, route plans, polling, cancellation races, cleanup reconciliation, and report downloads. Reset the new-assessment form by project identity. |
| `dashboard/src/components/{TargetForm,RoutePlanEditor}.tsx` | Source selection, operator profiles, unique route keys, per-route plugins, and required checks. Keep API validation authoritative. |
| `dashboard/src/components/{AssessmentDetails,EvidenceDetails,RouteResults,common}.tsx` | Execution/cleanup distinction, coverage, partial findings, evidence linkage, text rendering, errors, and pagination. Keep shared dashboard/report components. |
| `dashboard/src/hooks/{useAssessment,useReportDownload}.ts`, `dashboard/src/{reports.tsx,evidence.ts}` | Polling through pending cleanup, export aborts, late responses, HTML escaping, evidence grouping, and Blob lifecycle. Retain integrated report-safety tests. |
| `dashboard/src/styles.css`, `dashboard/index.html`, dashboard build/test configs | Responsive overflow, asset paths, strict TypeScript, hooks linting, browser configuration, and Vite proxy origins. Keep the existing configuration. |
| `dashboard/src/test/*`, dashboard unit tests, and `dashboard/e2e/*` | Shared synthetic records and behavior coverage. Keep critical workflow, CSP/browser, report-safety, and failure-path checks. |

Also reviewed the demo/service fixtures, documentation, Docker/Compose files,
dependency manifests/locks, and GitHub workflows. The demo remains a synthetic
assessment target; its presentation is outside the critical product test surface.

## Test selection and technology decisions

Removed 113 existing cases: 77 demo-server presentation/fixture cases, 17 redundant
schema round trips, 10 simple CLI forwarding cases, eight configuration/test-fixture
cases, and one duplicate frontend evidence-grouping case. Critical report and
assessment integration tests continue to cover serialization and evidence grouping.
Added 33 critical cases: 27 additional mount-boundary cases, one route-storage
failure, four unavailable-configuration cases, and one project-navigation case.

Keep Python 3.14, FastAPI/Pydantic 2, SQLAlchemy 2/PostgreSQL 18, React 19,
React Query 5, and the existing TypeScript 7 compiler. The `tsc` executable already
resolves to the native TypeScript 7 package; the TypeScript 6 compatibility package
supports the lint/tooling stack. The useful simplifications here are a reusable
Pydantic annotated type and React's keyed state reset. A framework, queue, or
database rewrite would add complexity without resolving a demonstrated defect.

## Verification

- Non-Docker backend: **1,037 passed** with disposable PostgreSQL databases.
- Dashboard unit tests: **57 passed**.
- Real Docker lifecycle, recovery, and service bundles: **12 passed**.
- Ruff lint/format, ESLint, TypeScript type checking, and Vite production build pass.
- API and runner Docker images build; service-bundle and process recovery checks
  use the packaged application.
- Live API boundary checks: **18 passed**, with no assessment/audit side effects.
- Browser acceptance: **47 passed**; three tests reach downloaded HTML reports and
  then fail with `ERR_BLOCKED_BY_ADMINISTRATOR` because managed Chromium blocks
  `file://` navigation. Their later offline assertions remain unverified here;
  report-generation and injection-safety unit tests pass. The browser policy and
  the critical browser tests remain intact.
- Static checks of all three downloaded HTML reports preserve their findings and
  restrictive CSP and contain no active content or links.

Commands follow `CONTRIBUTING.md`. Verification logs, live-boundary results, and
source-hash comparisons for all 40 packaged Python modules
are saved under ignored `artifacts/edge-review/`; browser traces and downloaded
reports are under ignored `app/dashboard/test-results/`.

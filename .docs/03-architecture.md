# Seireth - Architecture and Platform Design
## 9. High-Level Architecture

```text
                    +-------------------------+
                    | Next.js Web UI          |
                    | TypeScript              |
                    +------------+------------+
                                 |
                    +------------v------------+
                    | FastAPI API             |
                    | Orchestrator            |
                    +------+------------+-----+
                           |            |
                           v            v
                    PostgreSQL       Redis
                                        |
                                        v
                               Dramatiq Workers
                                        |
                                        v
                               Python Test Modules
                                        |
                                        v
                    +-------------------------+
                    | Go Sandbox Manager      |
                    | Environment lifecycle   |
                    | Resource limits         |
                    | Network restrictions    |
                    | Cleanup verification    |
                    +------------+------------+
                                 |
                                 v
                    +-------------------------+
                    | Disposable Test Target  |
                    | Docker initially        |
                    | Firecracker/Kata later  |
                    +-------------------------+
```

### Component relationship

```text
FastAPI orchestrator
    decides what assessment should run

Dramatiq workers
    execute approved security-test modules

Go sandbox manager
    controls how test environments are created,
    restricted, stopped, and destroyed

PostgreSQL
    stores authoritative platform data

Redis
    provides transient queue and worker coordination

Next.js
    provides the management and investigation interface
```

Security-test modules must not directly control the host or create unrestricted environments.

---


## 10. Repository Structure

The repository is built incrementally. The current implementation is kept
small, while the planned service boundaries are documented separately so the
tree does not contain empty placeholder directories.

### Current MVP-0 structure

```text
seireth/
|
|-- app/                      # FastAPI API, models, orchestration, plugins
|-- examples/
|   |-- demo-target/          # Project-owned vulnerable target
|-- tests/                    # Unit and API tests
|-- Dockerfile
|-- docker-compose.yml
|-- pyproject.toml
|-- README.md
|-- SECURITY.md
|-- CONTRIBUTING.md
|-- LICENSE
```

This is the implemented source layout for MVP-0. It intentionally keeps the
first vertical slice in one Python application while preserving clear
boundaries between the API, persistence, orchestration, plugins, and sandbox
interfaces.

### Planned expansion

```text
seireth/
|-- apps/
|   |-- api/                  # FastAPI application
|   |-- worker/               # Background assessment workers
|   |-- web/                  # Next.js dashboard
|
|-- services/
|   |-- sandbox-manager/      # Go sandbox lifecycle service
|
|-- packages/
|   |-- core/                 # Shared domain logic
|   |-- models/               # Shared data models and schemas
|   |-- test-sdk/             # Security-test module SDK
|   |-- orchestrator/         # Assessment execution logic
|   |-- evidence/             # Evidence collection and handling
|   |-- reporting/            # Report generation
|
|-- plugins/
|   |-- tls/
|   |-- security-headers/
|   |-- api-security/
|   |-- authentication/
|   |-- authorization/
|   |-- input-validation/
|   |-- sqli/
|   |-- dependencies/
|   |-- containers/
|
|-- infrastructure/
|   |-- docker/
|   |-- postgres/
|   |-- redis/
|   |-- development/
|
|-- examples/
|   |-- vulnerable-app/
|   |-- demo-target/
|   |-- example-plugin/
|
|-- tests/
|   |-- unit/
|   |-- integration/
|   |-- sandbox/
|   |-- authorization/
|   |-- plugins/
|
|-- docs/
|   |-- architecture/
|   |-- plugins/
|   |-- security/
|   |-- sandboxing/
|   |-- cra/
|-- scripts/
|

|
|-- docker-compose.yml
|-- README.md
|-- SECURITY.md
|-- CONTRIBUTING.md
|-- LICENSE
```

New top-level areas should be introduced when they have a real implementation
and an owner, not as placeholders. The exact repository structure may change
during implementation, but the separation between orchestration, test modules,
and sandbox management should remain clear.

---


## 28. Component Responsibilities

### FastAPI orchestrator

Responsible for:

- Authentication
- Authorization
- Project management
- Target registration
- Scope validation
- Test-run creation
- Queue submission
- Run status
- Findings management
- Remediation workflow
- Retest workflow
- Report generation
- Evidence metadata
- Audit events

### Python workers

Responsible for:

- Executing approved test modules
- Communicating with the sandbox manager
- Collecting results
- Normalizing findings
- Enforcing module timeouts
- Returning structured results

Workers must not bypass authorization or sandbox restrictions.

### Go sandbox manager

Responsible for:

- Creating test environments
- Applying resource limits
- Applying network restrictions
- Starting and stopping workloads
- Managing temporary resources
- Destroying environments
- Verifying cleanup
- Returning lifecycle status

### PostgreSQL

Stores:

- Projects
- Users
- Targets
- Target versions
- Authorization scopes
- Test profiles
- Test modules
- Test runs
- Sandboxes
- Findings
- Evidence
- Remediation records
- Retests
- Reports
- Audit events

### Redis

Used for:

- Job queue
- Worker coordination
- Short-lived progress state

Redis must not be the authoritative source for findings, audit events, or evidence.

### Frontend

Provides:

- Project dashboard
- Target registration
- Assessment creation
- Run progress
- Findings
- Remediation workflow
- Retesting
- Reports
- Evidence views
- Configuration

---


## 29. Data Model

Initial conceptual entities:

```text
Project
User
Target
TargetVersion
AuthorizationScope
TestProfile
TestModule
TestRun
Sandbox
Finding
FindingEvidence
Remediation
Retest
Report
EvidenceRecord
AuditEvent
```

Relationships:

```text
Project
 |-- Users
 |-- Targets
 |    |-- Target Versions
 |-- Authorization Scopes
 |-- Test Profiles
 |-- Test Runs
 |    |-- Sandbox
 |    |-- Findings
 |    |    |-- Evidence
 |    |-- Reports
 |-- Remediations
 |-- Retests
 |-- Evidence Records
 |-- Audit Events
```

Every security-sensitive record should include:

- Stable identifier
- Project ownership
- Creation timestamp
- Update timestamp
- Actor where applicable
- Target version where applicable
- Trace or assessment identifier where applicable

---


## 30. API Areas

Example API areas:

```text
/api/v1/projects
/api/v1/projects/{id}
/api/v1/targets
/api/v1/targets/{id}
/api/v1/target-versions
/api/v1/authorization-scopes
/api/v1/test-profiles
/api/v1/test-modules
/api/v1/test-runs
/api/v1/test-runs/{id}
/api/v1/test-runs/{id}/cancel
/api/v1/findings
/api/v1/findings/{id}
/api/v1/findings/{id}/retest
/api/v1/remediations
/api/v1/reports
/api/v1/evidence
/api/v1/audit-events
```

The API should use:

- OpenAPI documentation
- Consistent error responses
- Pagination
- Maximum page sizes
- Request-size limits
- Authentication
- Project-level authorization
- Input validation
- Rate limiting
- No internal stack traces in responses

---

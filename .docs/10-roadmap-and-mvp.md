# Seireth - Roadmap, MVP, and Long-Term Vision
## 33. Development Phases

### Phase 1: Foundation

- Repository structure
- FastAPI service
- PostgreSQL schema
- Basic authentication
- Project and target models
- Docker Compose
- Basic frontend shell
- Health checks
- OpenAPI contract

### Phase 2: Assessment lifecycle

- Authorization scope
- Assessment creation
- Redis queue
- Dramatiq worker
- Run status
- Cancellation
- Timeouts
- Basic audit events

### Phase 3: Sandbox management

- Go sandbox manager
- Docker environment creation
- Resource limits
- Network restrictions
- Environment teardown
- Cleanup verification

### Phase 4: First security tests

- TLS checks
- Security-header checks
- Dependency scanning
- Container scanning
- Safe input-validation tests
- Structured findings

### Phase 5: Reporting and remediation

- JSON reports
- SARIF reports
- HTML reports
- Findings dashboard
- Finding assignment
- Remediation status
- Retesting
- Regression comparison

### Phase 6: Security hardening

- Stronger sandbox isolation
- Improved secret handling
- Egress controls
- Fuzz testing
- Security regression tests
- Dependency and image scanning
- Signed artifacts
- Backup and recovery testing

### Phase 7: Evidence and CRA mapping

- Evidence data model
- Evidence collection
- Product-version traceability
- Vulnerability lifecycle records
- Secure-development evidence
- Remediation evidence
- Configurable CRA-related control mapping
- Evidence export

### Phase 8: Integrations

- GitHub integration
- CI/CD integration
- Issue creation
- Pull-request status checks
- External vulnerability scanners
- SIEM export

---


## 34. MVP Definition of Done

The first MVP is complete when:

- A user can create a project.
- A user can register an authorized containerized target.
- A user can define an explicit test scope.
- A user can select a passive or safe-active profile.
- An assessment can be queued.
- A disposable environment can be created.
- At least one security test can execute.
- Findings are stored in PostgreSQL.
- The environment is destroyed after execution.
- Cleanup is verified.
- An assessment has a complete audit history.
- JSON, SARIF, or HTML results can be generated.
- A finding can be assigned for remediation.
- A finding can be retested.
- Docker Compose starts the required services.
- The platform refuses tests without valid authorization or scope.
- Tests cover authorization, timeout, cancellation, cleanup, and failure behavior.

---


## 35. Initial Demonstration

The first demonstration should use a deliberately vulnerable application owned by the project.

Example:

```text
1. Register the vulnerable test application.
2. Register its container image or source repository.
3. Define the allowed test scope.
4. Select the safe-active profile.
5. Start an assessment.
6. Create an isolated environment.
7. Run security tests.
8. Detect a known vulnerability.
9. Verify the finding.
10. Store structured evidence.
11. Generate SARIF and HTML reports.
12. Destroy the environment.
13. Verify cleanup.
14. Apply a remediation.
15. Run the assessment again.
16. Show that the finding is resolved.
17. Export the assessment and remediation evidence.
```

The demonstration must not use third-party targets without explicit authorization.

---


## 37. Long-Term Vision

Seireth should evolve from a collection of security scanners into a security-validation platform.

```text
Build product
    ↓
Prepare authorized target
    ↓
Deploy isolated test environment
    ↓
Run security validation
    ↓
Discover vulnerabilities
    ↓
Create remediation work
    ↓
Retest changes
    ↓
Approve release
    ↓
Retain security evidence
    ↓
Validate future versions
```

The defining feature of Seireth should remain:

> **Run authorized security assessments against isolated software targets, verify the results, preserve the evidence, and destroy the environment when finished.**

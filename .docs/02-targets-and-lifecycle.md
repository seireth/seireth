# Seireth - Targets and Assessment Lifecycle
## 8. Supported Target Types

Seireth should support several target preparation modes rather than assuming that every application can be cloned.

### 8.1 Repository-based targets

Build and deploy an application from an authorized source repository and commit or tag.

### 8.2 Container-image targets

Test an authorized container image with a declared runtime configuration.

### 8.3 Docker Compose targets

Deploy a multi-service application with databases, queues, and supporting services.

### 8.4 Artifact-based targets

Test an authorized release package, binary, or deployment artifact.

### 8.5 Authorized staging targets

Test a remote staging environment when the user has explicitly declared the endpoint and scope.

Remote targets must have stricter authorization, network, and time controls than local disposable targets.

---


## 11. Assessment Lifecycle

Every assessment should follow a controlled lifecycle:

```text
Validate authorization
        ↓
Validate target and scope
        ↓
Prepare target
        ↓
Create sandbox
        ↓
Apply restrictions
        ↓
Start target
        ↓
Run discovery
        ↓
Run selected test modules
        ↓
Verify findings
        ↓
Collect evidence
        ↓
Stop target
        ↓
Destroy sandbox
        ↓
Verify cleanup
        ↓
Generate report
        ↓
Persist assessment result
```

The core platform owns sandbox lifecycle management. Test modules must never decide when the sandbox is destroyed.

Cleanup must execute when:

- A test module crashes
- A timeout occurs
- The target becomes unavailable
- A test fails
- The user cancels the assessment
- A worker exits unexpectedly
- The assessment is partially completed

An assessment must not be reported as fully successful if cleanup verification fails.

---


## 12. Authorization and Scope

Before execution, every assessment must define:

- Project or organization
- Target
- Target owner
- Authorized operator
- Scope
- Allowed hosts
- Allowed ports
- Allowed paths or endpoints
- Test profile
- Test modules
- Start time
- Expiration time
- Maximum duration
- CPU and memory limits
- Network policy
- Destructive-test permission
- Data-handling restrictions

The platform must reject:

- Targets without an owner
- Missing authorization
- Ambiguous scope
- Expired authorization
- Unbounded network scope
- Unrestricted internet scanning
- Production targets without explicit approval
- Destructive profiles without explicit authorization

---


## 13. Test Profiles

Users should be able to select a predefined profile instead of manually selecting every module.

### Passive

Read-only or low-interaction checks.

Examples:

- Dependency analysis
- SBOM generation
- TLS checks
- Configuration inspection
- Static metadata checks

### Safe active

Controlled requests that should not intentionally modify application data.

Examples:

- Security-header checks
- Input-validation checks
- Non-destructive injection detection
- Authentication boundary checks
- Authorization boundary checks
- API behavior checks

### Authenticated

Testing with explicitly supplied test credentials and a defined user scope.

Credentials must be temporary, scoped, protected, and removed after the assessment.

### Destructive

Tests that may modify or disrupt data or system state.

This profile must:

- Be disabled by default
- Require explicit authorization
- Require additional confirmation
- Use test data only
- Have strict scope and time limits
- Be clearly identified in reports
- Support emergency cancellation

Initial development should focus on passive and safe-active profiles.

---


## 21. Assessment Profiles

Profiles group test modules and define their safety characteristics.

Example profiles:

```text
profiles/
├── passive.yaml
├── safe-web.yaml
├── safe-api.yaml
├── authenticated.yaml
└── dependency-and-container.yaml
```

Example:

```text
SAFE-WEB
├── Discovery
├── Security headers
├── TLS
├── Input validation
├── Non-destructive SQL injection detection
└── Authentication boundary checks
```

A future profile may contain CRA-related evidence collection, but CRA should not be implemented as a vulnerability plugin. CRA support belongs in the evidence and standards-mapping layer.

Organizations may later define custom profiles.

---

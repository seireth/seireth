# Seireth - Sandboxing, Cleanup, and Security
## 16. Sandbox Model

The sandbox is a fundamental security boundary.

### Initial implementation

Use Docker for development and early deployments.

Where possible, use:

- Rootless containers
- Non-privileged users
- Read-only filesystems
- Dropped Linux capabilities
- Seccomp profiles
- AppArmor or SELinux
- CPU limits
- Memory limits
- Process limits
- Execution timeouts
- Restricted networks
- Default-deny egress
- No host Docker socket exposed to target workloads

### Stronger isolation

Later versions may support:

- Firecracker microVMs
- Kata Containers
- Dedicated worker hosts
- Ephemeral virtual machines
- Separate test networks

Containers are not automatically equivalent to a strong security boundary. The platform documentation must state the limitations of each sandbox backend.

### Assessment separation

```text
Assessment A → Sandbox A → Destroy

Assessment B → Sandbox B → Destroy

Assessment C → Sandbox C → Destroy
```

Tests must not interfere with one another.

---


## 17. Cleanup Verification

After every assessment, Seireth should verify:

- Test containers stopped
- Test containers removed
- Temporary volumes removed
- Temporary networks removed
- Worker processes terminated
- Temporary credentials revoked
- Temporary files removed
- Sandbox state is no longer accessible
- No unexpected resources remain

Cleanup results should be stored as part of the assessment record.

Possible cleanup states:

```text
NOT_STARTED
IN_PROGRESS
COMPLETED
FAILED
PARTIAL
REQUIRES_OPERATOR_ACTION
```

If cleanup fails, the platform must report it clearly and provide operator actions to resolve the remaining resources.

---


## 31. Security Requirements

Seireth itself is security-sensitive infrastructure.

Required protections include:

- Explicit target authorization
- Deny-by-default scope validation
- Authentication and authorization
- Project isolation
- Strong input validation
- Resource quotas
- Execution timeouts
- Network egress restrictions
- Secret redaction
- No plaintext secret storage
- No unrestricted host access
- No unrestricted internet scanning
- Secure defaults
- Dependency scanning
- Container scanning
- Signed releases where practical
- Audit logging
- Cleanup verification
- Emergency cancellation
- Backup and recovery
- Security disclosure process

The platform must fail closed when authorization, scope validation, or sandbox setup cannot be completed.

---


## 32. Audit Events

The platform should record:

- Project created
- Target registered
- Target version registered
- Assessment authorized
- Assessment started
- Assessment cancelled
- Assessment completed
- Assessment failed
- Sandbox created
- Sandbox destroyed
- Cleanup verified
- Finding created
- Finding updated
- Finding assigned
- Finding retested
- Finding resolved
- Report generated
- Report exported

Audit events should be:

- Structured
- Timestamped
- Searchable
- Trace-correlated
- Append-oriented
- Protected against unauthorized modification

If a required audit event cannot be persisted, the platform must report the failure rather than silently treating the action as successful.

---

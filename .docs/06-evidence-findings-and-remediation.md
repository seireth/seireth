# Seireth - Evidence, Findings, and Remediation
## 18. Evidence Model

Evidence is a first-class part of Seireth.

The evidence flow is:

```text
Test module
    ↓
Observation
    ↓
Verification
    ↓
Evidence
    ↓
Finding
```

Possible evidence includes:

- HTTP request and response
- Endpoint and parameter
- Sanitized application logs
- Screenshots
- Dependency metadata
- Container metadata
- Configuration state
- Verification results
- Sandbox metadata
- Test-module version
- Target version
- Assessment configuration

Only the minimum evidence required to demonstrate a finding should be retained.

Sensitive values must be redacted. Reports must not expose:

- Passwords
- Private keys
- Access tokens
- Authorization headers
- Unnecessary personal data
- Full production data
- Uncontrolled response bodies

---


## 19. Finding Model

A finding should include:

```text
Finding ID
Title
Severity
Confidence
Category
Target
Target version
Endpoint
Parameter
Description
Impact
Evidence
Reproduction information
Remediation guidance
Test module
Assessment
Status
Standards mappings
```

Suggested severity levels:

```text
INFO
LOW
MEDIUM
HIGH
CRITICAL
```

Suggested statuses:

```text
OPEN
CONFIRMED
FALSE_POSITIVE
IN_REMEDIATION
READY_FOR_RETEST
RESOLVED
REOPENED
ACCEPTED_RISK
```

Example:

```text
SEC-001

Title:
SQL injection in user search endpoint

Severity:
HIGH

Confidence:
HIGH

Target:
Example API v1.4.2

Endpoint:
/api/users

Evidence:
Sanitized request, response, and verification result

Remediation:
Use parameterized queries and validate input.

Mappings:
CWE
OWASP
CRA-related evidence category
```

A finding should not be considered resolved only because a user changes its status. Resolution should preferably be supported by a successful retest.

---


## 20. Remediation and Retesting

Users should be able to:

- Assign findings
- Add remediation notes
- Link code changes
- Link pull requests
- Mark findings ready for retest
- Re-run the original test
- Compare previous and current results
- Confirm remediation
- Reopen findings that remain reproducible

A retest should preserve:

- Original finding
- New target version
- Test module and version
- Test configuration
- Result
- Evidence
- Operator
- Timestamp
- Cleanup status

---

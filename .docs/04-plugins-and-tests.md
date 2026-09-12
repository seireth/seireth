# Seireth - Plugins, Test Categories, and Analysis
## 14. Plugin Architecture

Security tests should be implemented as independent, versioned modules.

A test module should provide:

```text
Module
├── Metadata
├── Input validation
├── Capability declaration
├── Discovery
├── Test execution
├── Finding verification
├── Evidence collection
└── Result generation
```

Example:

```text
plugins/sqli/
├── plugin.py
├── detector.py
├── verifier.py
├── evidence.py
├── manifest.yaml
└── tests/
```

Example manifest:

```yaml
name: sqli
version: 1.0.0
category: input-validation

capabilities:
  - http_client

targets:
  - web
  - api

risk: high
profile_requirements:
  - safe-active
```

Modules should declare their capabilities, such as:

- HTTP client
- Target logs
- Dependency metadata
- Source metadata
- Database metadata
- Temporary test credentials

The platform should restrict modules to their declared capabilities.

A module must not receive arbitrary host access, unrestricted filesystem access, or unrestricted network access.

---


## 15. Initial Test Categories

The first implementation should focus on bounded, useful tests:

- TLS configuration checks
- Security-header checks
- Dependency vulnerability scanning
- Container image scanning
- API schema validation
- Endpoint discovery
- Authentication checks
- Authorization boundary checks
- Input-validation checks
- Non-destructive SQL injection detection
- Cross-tenant access checks
- Regression tests for previously discovered findings

The platform should distinguish between:

- Suspected vulnerability
- Reproducible vulnerability
- Confirmed vulnerability
- False positive
- Accepted risk

Automated validation should not be presented as proof of complete security.

---


## 22. Dependency and SBOM Analysis

Dependency and software-supply-chain analysis should be supported as security-test capabilities.

The platform may eventually support:

- Dependency discovery
- Known vulnerability detection
- SBOM generation
- SPDX
- CycloneDX
- Container image analysis
- Dependency risk reporting
- License metadata

Example:

```text
Dependencies analyzed: 347

Critical: 2
High:     7
Medium:  31

SBOM:
SPDX generated
CycloneDX generated
```

Seireth should integrate existing vulnerability sources and scanners instead of initially building a custom vulnerability database.

---

# Seireth - CRA and Standards Mapping
## 23. CRA and Standards Mapping

Security findings must be separated from standards mappings.

A finding may map to:

```text
Finding
├── CWE
├── OWASP
├── CRA-related evidence category
└── Custom framework
```

This prevents security-test modules from becoming tightly coupled to a single regulation or framework.

### Cyber Resilience Act

The Cyber Resilience Act is a long-term evidence and mapping target for Seireth.

Seireth may help collect technical evidence related to:

- Secure development
- Security testing
- Vulnerability discovery
- Vulnerability handling
- Remediation
- Regression testing
- Product-version traceability
- Security maintenance
- Incident investigation
- Security documentation

Seireth must not claim to automatically make a product or organization compliant with the CRA.

Reports should distinguish between:

```text
Automatically verified
Evidence collected
Partially assessed
Not assessed
Manual review required
```

Example:

```text
Evidence category:
Vulnerability-handling process

Status:
PARTIAL

Evidence collected:
- Security findings recorded
- Remediation tracked
- Retesting supported

Manual review required:
- Organizational disclosure procedure
- Legal applicability
- Product classification
```

CRA mappings should be configurable because regulatory guidance, standards, product categories, and organizational obligations may change.

---


## 36. CRA Positioning

The Cyber Resilience Act is a relevant long-term driver because it introduces cybersecurity requirements for products with digital elements, including requirements related to secure development, vulnerability handling, and lifecycle security.

Seireth may help organizations collect technical evidence related to:

- Security testing
- Vulnerability discovery
- Vulnerability handling
- Remediation
- Regression testing
- Product-version traceability
- Security maintenance
- Incident investigation
- Secure-development activities

Seireth does not provide automatic legal compliance.

The platform should clearly distinguish between:

```text
Technical evidence produced by Seireth
```

and:

```text
Complete legal or regulatory compliance
```

CRA applicability depends on the product, manufacturer, organization, product category, role in the supply chain, and legal interpretation.

CRA mappings should be configurable and reviewed as regulations, guidance, standards, and product requirements evolve.

---

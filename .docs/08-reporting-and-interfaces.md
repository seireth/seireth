# Seireth - Reporting, Web UI, and CLI
## 24. Reporting

Seireth should produce reports for both technical and management audiences.

Recommended report sections:

```text
1. Executive summary
2. Target and version
3. Authorization and scope
4. Assessment methodology
5. Test profile
6. Environment
7. Risk summary
8. Findings
9. Evidence
10. Remediation status
11. Retest results
12. Dependency and SBOM results
13. Standards mappings
14. CRA-related evidence
15. Manual review items
16. Cleanup status
17. Appendix
```

Supported formats:

```text
JSON
SARIF
HTML
Markdown
PDF later
```

Reports should include:

- Target identity
- Version, commit, image, or artifact
- Assessment identifier
- Scope
- Profile
- Test modules and versions
- Start and end times
- Findings
- Severity and confidence
- Evidence references
- Remediation status
- Cleanup status
- Environment metadata

---


## 25. Web UI

The web UI should feel like a professional security-validation platform rather than a generic attack dashboard.

Primary sections:

```text
Dashboard
Projects
Targets
Assessments
Findings
Remediation
Reports
Test Modules
Evidence
Settings
```

### Dashboard

Display:

- Total projects
- Total targets
- Active assessments
- Critical and high findings
- Recent assessments
- Open remediation items
- Failed cleanup operations
- Overall risk trends

### Assessment view

```text
Assessment #1042

Target:
Example Application

Version:
v1.4.2

Profile:
Safe Web

Status:
Running

âœ“ Authorization
âœ“ Preparation
âœ“ Sandbox
âœ“ Discovery
â— Input validation
â—‹ Reporting
â—‹ Cleanup

Findings:
1 High
3 Medium
```

### Finding view

Display:

- Severity
- Confidence
- Description
- Impact
- Affected target
- Evidence
- Verification status
- Remediation
- Retest history
- Standards mappings
- Assessment information

---


## 26. CLI

The CLI should remain useful without the web UI.

Example:

```bash
seireth project create example-project
```

```bash
seireth target add --project example-project ./my-app
```

```bash
seireth assess my-app --profile safe-web
```

Example output:

```text
Seireth

Target       my-app
Profile      safe-web
Assessment   #1042

[âœ“] Authorization validated
[âœ“] Preparing target
[âœ“] Creating sandbox
[âœ“] Discovery
[âœ“] Security checks
[!] Input validation finding
[âœ“] Evidence collected
[âœ“] Sandbox destroyed
[âœ“] Cleanup verified

Findings

HIGH       1
MEDIUM     3
LOW        2

Reports:
./reports/1042/index.html
./reports/1042/results.sarif
```

---

# Seireth - Technology Stack
## 27. Technology Stack

| Area | Technology | Purpose |
|---|---|---|
| Orchestration API | Python | Fast development and security-tool integration |
| API framework | FastAPI | REST API and request validation |
| Security-test modules | Python | HTTP, parsing, asynchronous execution, and security ecosystem |
| Sandbox manager | Go | Environment lifecycle, concurrency, and reliability |
| Initial sandbox | Docker | Local development and initial deployments |
| Stronger isolation | Firecracker or Kata Containers | Later production isolation |
| Frontend | Next.js and TypeScript | Dashboard, findings, runs, and reports |
| Database | PostgreSQL | Targets, runs, findings, evidence, and metadata |
| Queue | Redis initially | Job scheduling and transient coordination |
| Workers | Dramatiq | Background assessment execution |
| Reverse proxy | Caddy or Nginx | TLS termination and routing |
| Reports | JSON, SARIF, HTML, Markdown | Automation and human review |
| Deployment | Docker Compose initially | Local and single-host deployment |
| Production orchestration | Kubernetes later | Scaling workers and sandboxes |
| API contract | OpenAPI | Component communication and documentation |
| Python testing | Pytest | Unit and integration tests |
| Go testing | Go testing | Sandbox-manager tests |
| Integration testing | Testcontainers | Real service integration tests |
| CI/CD | GitHub Actions | Build, test, scan, and release |
| Dependency security | Dependabot and OSV-compatible tools | Dependency monitoring |
| Container security | Trivy or equivalent | Image and filesystem scanning |

Dramatiq is the initial worker recommendation. Celery may be evaluated later if the workflow requires more advanced distributed task features.

---

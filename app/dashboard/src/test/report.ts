import type { AssessmentReport, Evidence } from "../api/types";

const cookieEvidence = {
  id: "e", finding_id: "f", kind: "http-response",
  data: { url: "http://demo.test/", header: "set-cookie", cookie_name: "original", rule_id: "samesite-none-without-secure", samesite: "none", secure: false },
} satisfies Evidence;

export const reportFixture: AssessmentReport = {
  schema_version: 1,
  generated_at: "2026-10-07T12:01:00Z",
  project: { id: "p", name: "<script>window.syntheticInjected=true</script>", created_at: "2026-10-07T12:00:00Z" },
  target: { id: "t", project_id: "p", name: "Demo", image: "seireth/demo-app:local", kind: "docker", url: "http://demo.test/" },
  assessment: {
    id: "a", project_id: "p", target_id: "t", url: "http://demo.test/",
    created_at: "2026-10-07T12:00:00Z", plugins: ["cookie-security"],
    status: "completed", cleanup_pending: false,
    plan_snapshot: {
      version: 1, target: { id: "t", project_id: "p", name: "Demo", kind: "docker", image: "seireth/demo-app:local", url: "http://demo.test/", launch_profile: null, network_profile: null, trust_profile: null },
      routes: [{ key: "session", url: "http://demo.test/", plugins: ["cookie-security"], request_profile: null,
        request: { headers: {}, secret_headers: {}, follow_redirects: false }, request_seconds: 10,
        expected: { statuses: [200], media_types: ["text/html"], final_url: "http://demo.test/" },
        required_checks: ["cookie-security:samesite-none-without-secure"], required_checks_explicit: true,
        analysis: { session_cookies: [], expected_cookies: ["original"] } }],
      plugins: [{ id: "cookie-security", version: "1.0.0" }],
      images: { target: "sha256:" + "1".repeat(64), runner: "sha256:" + "2".repeat(64) },
      launch: {
        target: { image: "seireth/demo-app:local", command: [], environment: {}, secret_environment: {}, uid: 65532, gid: 65532, volumes: [], depends_on: [], readiness: { kind: "tcp", port: 80, path: "/", status: 200 }, tmpfs: [], memory: "256m", cpus: 0.5, pids: 64 },
        services: {}, startup_seconds: 30,
      },
      network: null, ca: null, ca_fingerprint: null, control_endpoints: [], timeout_seconds: 60, cleanup_seconds: 60,
      runner_limits: { memory: "256m", cpus: 0.5, pids: 64 }, policy: "strict-v1", baseline: null,
    },
    result: {
      execution_outcome: "completed", coverage: { complete: true }, partial: false,
      verdict: { policy: "strict-v1", status: "blocked", reasons: ["finding observed"] },
      comparison: { status: "not_requested" },
      sandbox_backend: "docker", cleanup_verified: true, cleanup_reason: null,
      execution: {
        started_at: "2026-10-07T12:00:00Z", deadline_at: "2026-10-07T12:01:00Z",
        target: { id: "t", project_id: "p", name: "Demo", image: "seireth/demo-app:local", kind: "docker", url: "http://demo.test/" },
        plugins: [{ id: "cookie-security", version: "1.0.0" }],
      },
      completed_at: "2026-10-07T12:00:30Z", attempt: 1, finding_count: 1,
      routes: [{ id: "route-id", key: "session", url: "http://demo.test/", status: "completed",
        response: { status_code: 200, media_type: "text/html", url: "http://demo.test/", redirects: [] },
        plugins: [{ id: "cookie-security", finding_count: 1, checks: [{ rule_id: "samesite-none-without-secure", status: "failed", reason: "Observed cookie lacks Secure." }] }], finding_count: 1,
        coverage: { complete: true, expected_response: true, missing_checks: [], failed_checks: ["cookie-security:samesite-none-without-secure"] } }],
    },
  },
  findings: [{ id: "f", route_result_id: "route-id", plugin: "cookie-security", title: "SameSite configuration", severity: "low", description: "<img src=x onerror=alert(1)>", remediation: "Set Secure." }],
  evidence: [cookieEvidence],
};

export const multiFindingReport: AssessmentReport = {
  ...reportFixture,
  assessment: {
    ...reportFixture.assessment,
    plugins: ["http-security-headers", "cookie-security"],
    plan_snapshot: {
      ...reportFixture.assessment.plan_snapshot,
      plugins: [{ id: "http-security-headers", version: "1.0.0" }, { id: "cookie-security", version: "1.0.0" }],
      routes: reportFixture.assessment.plan_snapshot.routes.map(route => ({ ...route, plugins: ["http-security-headers", "cookie-security"] })),
    },
    result: {
      ...reportFixture.assessment.result!, finding_count: 3,
      execution: { ...reportFixture.assessment.result.execution!, plugins: [{ id: "http-security-headers", version: "1.0.0" }, { id: "cookie-security", version: "1.0.0" }] },
      routes: reportFixture.assessment.result!.routes.map(route => ({ ...route, finding_count: 3, plugins: [{id: "http-security-headers", finding_count: 0, checks: []}, {id: "cookie-security", finding_count: 3, checks: []}] })),
    },
  },
  findings: [
    reportFixture.findings[0],
    { ...reportFixture.findings[0], id: "other", title: "Other cookie configuration" },
    { ...reportFixture.findings[0], id: "empty", title: "Finding without evidence" },
  ],
  evidence: [
    { ...cookieEvidence, id: "z-original" },
    { ...cookieEvidence, id: "a-other", finding_id: "other", data: { ...cookieEvidence.data, cookie_name: "other" } },
    { ...cookieEvidence, id: "b-second", data: { ...cookieEvidence.data, cookie_name: "second" } },
  ],
};

export const routeReportFixture: AssessmentReport = {
  ...reportFixture,
  schema_version: 1,
  assessment: {
    ...reportFixture.assessment,
    result: {
      ...reportFixture.assessment.result!,
      execution_outcome: "completed",
      routes: [{
        id: "route-id", key: "session", url: reportFixture.assessment.url, status: "completed",
        finding_count: 1,
        response: { status_code: 200, media_type: "text/html", url: reportFixture.assessment.url, redirects: [] },
        plugins: [{ id: "cookie-security", finding_count: 1,
          checks: [{ rule_id: "samesite-none-without-secure", status: "failed", reason: "Cookie attributes evaluated." }] }],
        coverage: { complete: true, expected_response: true, missing_checks: [], failed_checks: ["cookie-security:samesite-none-without-secure"] },
      }],
    },
  },
  findings: [{ ...reportFixture.findings[0], route_result_id: "route-id" }],
};

export function blobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsText(blob);
  });
}

export const cspEvidenceFixture = {
  id: "csp-evidence", finding_id: "csp-inline", kind: "http-response",
  data: {
    url: "https://example.test/", header: "content-security-policy",
    rule_id: "csp-inline-scripts", status_code: 200, media_type: "text/html",
    policy_count: 2,
    observations: [
      { policy_index: 1, context: "inline-script", directive: "script-src-elem", condition: "unsafe-inline" },
      { policy_index: 2, context: "inline-script", directive: null, condition: "missing-directive" },
      { policy_index: 1, context: "script-attribute", directive: "script-src-attr", condition: "unsafe-inline" },
      { policy_index: 2, context: "script-attribute", directive: null, condition: "missing-directive" },
    ],
  },
} satisfies Evidence;

export const cspReportFixture: AssessmentReport = {
  ...reportFixture,
  assessment: {
    ...reportFixture.assessment, plugins: ["csp-policy"],
    plan_snapshot: {
      ...reportFixture.assessment.plan_snapshot,
      plugins: [{ id: "csp-policy", version: "1.0.0" }],
      routes: reportFixture.assessment.plan_snapshot.routes.map(route => ({ ...route, plugins: ["csp-policy"],
        analysis: { session_cookies: [], expected_cookies: [] },
        required_checks: ["csp-policy:csp-script-sources", "csp-policy:csp-inline-scripts", "csp-policy:csp-eval"] })),
    },
    result: {
      ...reportFixture.assessment.result!, finding_count: 1,
      execution: { ...reportFixture.assessment.result.execution!, plugins: [{ id: "csp-policy", version: "1.0.0" }] },
      routes: reportFixture.assessment.result!.routes.map(route => ({ ...route, plugins: [{ id: "csp-policy", finding_count: 1, checks: [
        { rule_id: "csp-script-sources", status: "passed", reason: "No covered weakness identified." },
        { rule_id: "csp-inline-scripts", status: "failed", reason: "Observed headers permit arbitrary inline scripts." },
        { rule_id: "csp-eval", status: "passed", reason: "No covered weakness identified." },
      ] }] })),
    },
  },
  findings: [{
    id: "csp-inline", route_result_id: "route-id", plugin: "csp-policy", title: "Unrestricted CSP inline script execution",
    severity: "medium", description: "Observed headers permit inline scripts; document content was not inspected.",
    remediation: "Remove effective unsafe-inline permissions.",
  }],
  evidence: [cspEvidenceFixture],
};

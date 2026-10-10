import type { AssessmentReport, Evidence } from "../api/types";

const cookieEvidence = {
  id: "e", finding_id: "f", kind: "http-response",
  data: { url: "http://demo.test/", header: "set-cookie", cookie_name: "original", rule: "samesite-none-without-secure", samesite: "none", secure: false },
} satisfies Evidence;

export const reportFixture: AssessmentReport = {
  schema_version: 1,
  generated_at: "2026-10-07T12:01:00Z",
  project: { id: "p", name: "<script>window.syntheticInjected=true</script>", created_at: "2026-10-07T12:00:00Z" },
  target: { id: "t", project_id: "p", name: "Demo", image: "seireth/demo-app:local", url: "http://demo.test/" },
  assessment: {
    id: "a", project_id: "p", target_id: "t", url: "http://demo.test/",
    created_at: "2026-10-07T12:00:00Z", plugins: ["cookie-security"],
    status: "completed", cleanup_pending: false,
    result: {
      sandbox_backend: "inmemory", cleanup_verified: true, cleanup_reason: null,
      completed_at: "2026-10-07T12:00:30Z", attempt: 1, finding_count: 1,
      response: { status_code: 200, media_type: "text/html" },
      plugins: [{ id: "cookie-security", finding_count: 1 }],
    },
  },
  findings: [{ id: "f", plugin: "cookie-security", title: "SameSite configuration", severity: "low", description: "<img src=x onerror=alert(1)>", remediation: "Set Secure." }],
  evidence: [cookieEvidence],
};

export const multiFindingReport: AssessmentReport = {
  ...reportFixture,
  assessment: {
    ...reportFixture.assessment,
    plugins: ["http-security-headers", "cookie-security"],
    result: {
      ...reportFixture.assessment.result, finding_count: 3,
      plugins: [{ id: "http-security-headers", finding_count: 0 }, { id: "cookie-security", finding_count: 3 }],
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

export function blobText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsText(blob);
  });
}

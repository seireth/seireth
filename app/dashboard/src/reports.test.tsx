import { act, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { downloadBlob, htmlReport } from "./reports";
import { multiFindingReport, reportFixture } from "./test/report";

function documentFor(report = reportFixture) {
  let html = "";
  act(() => { html = htmlReport(report); });
  expect(html).toMatch(/^<!doctype html>/);
  return new DOMParser().parseFromString(html, "text/html");
}

it("renders a complete offline report using escaped shared finding and evidence views", () => {
  const document = documentFor();
  expect(document.body.textContent).toContain(reportFixture.project.name);
  expect(document.body.textContent).toContain(reportFixture.findings[0].description);
  expect(document.body.textContent).toContain("Set Secure.");
  expect(document.body.textContent).toContain("original");
  expect(document.body.textContent).toContain("Simulated assessment");
  expect(document.body.textContent).toContain("2026-10-07T12:01:00.000Z");
  expect(document.querySelector("details")?.open).toBe(true);
  expect(document.querySelector("style")?.textContent).toContain("@media print");
  expect(document.querySelector("script, img, link, [href], [src]")).toBeNull();
  expect(document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute("content")).toContain("default-src 'none'");
});

it("assigns interleaved evidence to its finding and preserves request metadata", () => {
  const report = {
    ...multiFindingReport,
    target: { ...multiFindingReport.target, url: "http://demo.test/?text=<img src=x onerror=alert(1)>" },
    assessment: { ...multiFindingReport.assessment, url: "http://demo.test/?text=<script>synthetic</script>" },
  };
  const document = documentFor(report);
  const articles = Array.from(document.querySelectorAll<HTMLElement>(".finding"));
  expect(articles).toHaveLength(3);
  expect(Array.from(articles[0].querySelectorAll(".evidence"), (region) => region.textContent))
    .toEqual([expect.stringContaining("original"), expect.stringContaining("second")]);
  expect(articles[1].querySelectorAll(".evidence")).toHaveLength(1);
  expect(articles[1].querySelector(".evidence")?.textContent).toContain("other");
  expect(articles[2].querySelector(".evidence")).toBeNull();
  expect(Array.from(document.querySelectorAll("details")).every((details) => details.open)).toBe(true);
  const metadata = within(document.querySelector<HTMLElement>('[aria-label="Report metadata"]')!);
  expect(metadata.getByText("Target URL").nextElementSibling?.textContent).toBe(report.target.url);
  expect(metadata.getByText("Assessment URL").nextElementSibling?.textContent).toBe(report.assessment.url);
  expect(metadata.getByText("Checks").nextElementSibling?.textContent).toBe("http-security-headers, cookie-security");
  expect(metadata.getByText("Assessment ID").nextElementSibling?.textContent).toBe(report.assessment.id);
  expect(metadata.getByText("Target image").nextElementSibling?.textContent).toBe(report.target.image);
  expect(metadata.getByText("Created at (UTC)").nextElementSibling?.textContent).toBe("2026-10-07T12:00:00.000Z");
  expect(metadata.getByText("Generated at (UTC)").nextElementSibling?.textContent).toBe("2026-10-07T12:01:00.000Z");
  expect(document.querySelector("script, img")).toBeNull();
});

it.each([
  ["2026-10-07T12:00:30Z", "2026-10-07T12:00:30.000Z"],
  ["2026-10-07T12:00:30+00:00", "2026-10-07T12:00:30.000Z"],
  ["2026-10-07T12:00:30.123456+02:30", "2026-10-07T09:30:30.123Z"],
  ["2026-10-07T12:00:30-05:30", "2026-10-07T17:30:30.000Z"],
  ["2026-10-07T12:00:30.1Z", "2026-10-07T12:00:30.100Z"],
])("renders the supported completion timestamp %s in UTC", (completed_at, expected) => {
  const document = documentFor({ ...reportFixture, assessment: {
    ...reportFixture.assessment, result: { ...reportFixture.assessment.result, completed_at },
  } });
  expect(document.body.textContent).toContain(expected);
});

it.each(["created_at", "completed_at", "generated_at"] as const)(
  "rejects a failed render caused by %s instead of returning an empty report", (field) => {
    const invalid = "20261007T120000+0000";
    const report = {
      ...reportFixture,
      generated_at: field === "generated_at" ? invalid : reportFixture.generated_at,
      assessment: {
        ...reportFixture.assessment,
        created_at: field === "created_at" ? invalid : reportFixture.assessment.created_at,
        result: { ...reportFixture.assessment.result,
          completed_at: field === "completed_at" ? invalid : reportFixture.assessment.result?.completed_at,
        },
      },
    };
    // act reroutes root errors, so exercise the same error callback as the browser.
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", false);
    expect(() => htmlReport(report)).toThrow("Could not generate the HTML report.");
  },
);

it("retains skipped and inconclusive outcomes with zero findings", () => {
  const report = { ...reportFixture, findings: [], evidence: [], assessment: {
    ...reportFixture.assessment, result: { ...reportFixture.assessment.result,
      plugins: [{ id: "http-security-headers", finding_count: 0, checks: [
        { rule_id: "content-security-policy", status: "skipped" as const, reason: "Not a document." },
        { rule_id: "framing-protection", status: "inconclusive" as const, reason: "Media type unknown." },
      ] }],
    },
  } };
  const document = documentFor(report);
  expect(document.body.textContent).toContain("No covered violations were identified. This does not certify security.");
  expect(document.querySelector(".check-skipped")?.textContent).toBe("skipped");
  expect(document.querySelector(".check-inconclusive")?.textContent).toBe("inconclusive");
});

it("exports missing execution results and pending cleanup without manufacturing outcomes", () => {
  const missing = documentFor({ ...reportFixture, findings: [], evidence: [], assessment: { ...reportFixture.assessment, status: "cancelled", result: null } });
  expect(missing.body.textContent).toContain("No execution outcome");
  expect(missing.body.textContent).toContain("This assessment produced no persisted findings.");
  expect(missing.body.textContent).not.toContain("Completed at (UTC)");
  const pending = documentFor({ ...reportFixture, assessment: { ...reportFixture.assessment, status: "failed", cleanup_pending: true, result: { error: "Execution failed", cleanup_verified: false, cleanup_reason: "Unknown outcome" } } });
  expect(pending.body.textContent).toContain("Pending verification");
  expect(pending.body.textContent).toContain("Unknown outcome");
  expect(pending.body.textContent).toContain("Execution failed");
});

it("removes the download anchor and releases its URL even if clicking fails", async () => {
  const revokeObjectURL = vi.fn();
  const createObjectURL = vi.fn(() => "blob:report");
  vi.stubGlobal("URL", class extends URL { static createObjectURL = createObjectURL; static revokeObjectURL = revokeObjectURL; });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => { throw new Error("download failed"); });
  try {
    expect(() => downloadBlob(new Blob(["report"]), "report.json")).toThrow("download failed");
    expect(document.querySelector("a[download]")).toBeNull();
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:report"));
  } finally { click.mockRestore(); }
});

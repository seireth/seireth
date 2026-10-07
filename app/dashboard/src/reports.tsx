import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import type { AssessmentReport } from "./api/types";
import { AssessmentSummary, EmptyFindings, FindingDetails, ResponseChecks } from "./components/AssessmentDetails";
import { EvidenceDetails } from "./components/EvidenceDetails";
import dashboardStyles from "./styles.css?inline";

const reportStyles = `
.report { max-width: 1000px; margin: 24px auto; padding: 0 20px; }
.report > section { margin-bottom: 24px; }
.report dd { overflow-wrap: anywhere; }
@media print {
  :root { color-scheme: light; color: #111; background: white;
    --muted: #333; --border: #bbb; --accent: #175444; }
  .report { margin: 0; max-width: none; padding: 0; }
  .report .panel, .report .evidence { background: white; color: #111; }
  .report .badge { color: #111; background: transparent; }
  .report .finding { break-inside: avoid; }
}`;

function ReportContent({ report }: { report: AssessmentReport }) {
  const { assessment, project, target, findings, evidence } = report;
  return (
    <main className="report">
      <header className="page-header"><div>
        <h1>SEIRETH assessment report</h1>
        <p>{project.name} / {target.name}</p>
      </div></header>
      <section className="panel" aria-label="Report metadata">
        <h2>Assessment request</h2>
        <dl>
          <dt>Assessment ID</dt><dd>{assessment.id}</dd>
          <dt>Project ID</dt><dd>{project.id}</dd>
          <dt>Target ID</dt><dd>{target.id}</dd>
          <dt>Target image</dt><dd>{target.image}</dd>
          <dt>Target URL</dt><dd>{target.url}</dd>
          <dt>Assessment URL</dt><dd>{assessment.url}</dd>
          <dt>Checks</dt><dd>{assessment.plugins.join(", ")}</dd>
          <dt>Created at (UTC)</dt><dd>{new Date(assessment.created_at).toISOString()}</dd>
          {assessment.result?.completed_at && <><dt>Completed at (UTC)</dt><dd>{new Date(assessment.result.completed_at).toISOString()}</dd></>}
          {assessment.result?.attempt !== undefined && <><dt>Attempt</dt><dd>{assessment.result.attempt}</dd></>}
          <dt>Generated at (UTC)</dt><dd>{new Date(report.generated_at).toISOString()}</dd>
          <dt>Report schema version</dt><dd>{report.schema_version}</dd>
        </dl>
        <p>This report is a snapshot. Later cleanup reconciliation may change subsequent reports.</p>
        {assessment.result?.sandbox_backend === "inmemory" && <p>Simulated assessment: the in-memory backend performs no target networking.</p>}
        {assessment.result?.error && <p className="error">{assessment.result.error}</p>}
      </section>
      <AssessmentSummary assessment={assessment} findingCount={findings.length} />
      <ResponseChecks result={assessment.result} />
      <section className="findings-section">
        <h2>Findings and evidence</h2>
        {findings.length === 0 ? <EmptyFindings status={assessment.status} /> : findings.map((finding) => (
          <FindingDetails key={finding.id} finding={finding} expanded>
            <EvidenceDetails evidence={evidence.filter((entry) => entry.finding_id === finding.id)} />
          </FindingDetails>
        ))}
      </section>
    </main>
  );
}

export function htmlReport(report: AssessmentReport): string {
  const container = document.createElement("div");
  let renderFailed = false;
  const root = createRoot(container, {
    onUncaughtError: () => { renderFailed = true; },
  });
  try {
    flushSync(() => root.render(<ReportContent report={report} />));
    if (renderFailed) throw new Error("Could not generate the HTML report.");
    const output = document.implementation.createHTMLDocument("SEIRETH assessment report");
    output.documentElement.lang = "en";
    const charset = output.createElement("meta");
    charset.setAttribute("charset", "utf-8");
    const viewport = output.createElement("meta");
    viewport.name = "viewport";
    viewport.content = "width=device-width, initial-scale=1";
    const policy = output.createElement("meta");
    policy.httpEquiv = "Content-Security-Policy";
    policy.content = "default-src 'none'; style-src 'unsafe-inline'";
    const style = output.createElement("style");
    style.textContent = dashboardStyles + reportStyles;
    output.head.prepend(charset, viewport, policy);
    output.head.append(style);
    output.body.append(container.cloneNode(true));
    return "<!doctype html>\n" + output.documentElement.outerHTML;
  } finally {
    root.unmount();
  }
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  try {
    document.body.append(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    // Let the browser consume the download before releasing its backing URL.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

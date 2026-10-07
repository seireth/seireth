import type { ReactNode } from "react";
import type { Assessment, Finding, Result, Status } from "../api/types";
import { Empty } from "./common";

export function AssessmentSummary({ assessment, findingCount }: {
  assessment: Assessment;
  findingCount?: number;
}) {
  return (
    <section className="summary-grid">
      <div className="panel metric">
        <span>Execution</span>
        <strong>{assessment.status}</strong>
        <small>{assessment.result?.sandbox_backend || "Awaiting outcome"}</small>
      </div>
      <div className="panel metric">
        <span>Cleanup</span>
        <strong>{assessment.cleanup_pending ? "Pending verification" : assessment.result?.cleanup_verified ? "Verified" : "No execution outcome"}</strong>
        <small>{assessment.result?.cleanup_reason || "Cleanup is checked independently of execution."}</small>
      </div>
      <div className="panel metric">
        <span>Findings</span>
        <strong>{findingCount ?? "—"}</strong>
        <small>{assessment.plugins.length} selected plugins</small>
      </div>
    </section>
  );
}

export function ResponseChecks({ result }: { result: Result | null }) {
  if (!result?.response) return null;
  return (
    <section className="panel" aria-label="Response and check outcomes">
      <h2>Response and check outcomes</h2>
      <dl>
        <dt>HTTP status</dt><dd>{result.response.status_code}</dd>
        <dt>Declared media type</dt><dd>{result.response.media_type ?? "Unknown"}</dd>
      </dl>
      <p>Outcomes cover only the listed rules and declared response metadata.</p>
      {result.plugins?.filter((plugin) => plugin.checks?.length).map((plugin) => (
        <div key={plugin.id}>
          <h3>{plugin.id}</h3>
          <ul className="check-outcomes">
            {plugin.checks?.map((check) => (
              <li key={check.rule_id}>
                <span className={`badge check-${check.status}`}>{check.status}</span>{" "}
                <strong>{check.rule_id}</strong><p>{check.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

export function EmptyFindings({ status }: { status: Status }) {
  return <Empty>{status === "completed"
    ? "No covered violations were identified. This does not certify security."
    : "This assessment produced no persisted findings."}</Empty>;
}

export function FindingDetails({ finding, children, expanded = false }: {
  finding: Finding;
  children: ReactNode;
  expanded?: boolean;
}) {
  return (
    <article className="panel finding">
      <header>
        <span className={`badge severity ${finding.severity}`}>{finding.severity}</span>
        <span className="eyebrow">{finding.plugin}</span>
      </header>
      <h3>{finding.title}</h3><p>{finding.description}</p>
      <h4>Remediation</h4><p>{finding.remediation}</p>
      <details open={expanded || undefined}>
        <summary>Evidence</summary>{children}
      </details>
    </article>
  );
}

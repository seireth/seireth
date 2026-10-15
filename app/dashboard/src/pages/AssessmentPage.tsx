import { useEffect, useMemo, useRef } from "react";
import { Link, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../api/client";
import { useResource } from "../api/queries";
import type {
  EvidenceResponse,
  Project,
  Results,
} from "../api/types";
import { date, ErrorMessage, StatusBadge } from "../components/common";
import {
  AssessmentRequestFields,
  AssessmentSummary,
  EmptyFindings,
  ExecutionMetadata,
  FindingDetails,
  IncompleteExecution,
} from "../components/AssessmentDetails";
import { EvidenceDetails } from "../components/EvidenceDetails";
import { groupEvidenceByFinding } from "../evidence";
import { terminal, useAssessment } from "../hooks/useAssessment";
import { useReportDownload } from "../hooks/useReportDownload";
import { AssessmentSource, RouteResults } from "../components/RouteResults";

export default function AssessmentPage() {
  const { assessmentId = "" } = useParams();
  const client = useQueryClient();
  const run = useAssessment(assessmentId);
  const assessment = run.data;
  const finished = !!assessment && terminal(assessment.status);
  const results = useResource<Results>(
    `/assessments/${assessmentId}/results`,
    finished,
  );
  const evidence = useResource<EvidenceResponse>(
    `/assessments/${assessmentId}/evidence`,
    finished && !assessment?.cleanup_pending,
  );
  const evidenceByFinding = useMemo(
    () => groupEvidenceByFinding(evidence.data?.evidence ?? []),
    [evidence.data?.evidence],
  );
  const project = useResource<Project>(
    `/projects/${assessment?.project_id}`,
    !!assessment,
  );
  const report = useReportDownload(assessmentId);
  const previousCleanup = useRef(assessment?.cleanup_pending);
  useEffect(() => {
    if (previousCleanup.current && assessment?.cleanup_pending === false) {
      void client.invalidateQueries({ queryKey: ["/assessments/" + assessmentId + "/results"] });
      void client.invalidateQueries({ queryKey: ["/assessments/" + assessmentId + "/evidence"] });
    }
    previousCleanup.current = assessment?.cleanup_pending;
  }, [assessment?.cleanup_pending, assessmentId, client]);
  const cancel = useMutation({
    mutationFn: () => post(`/assessments/${assessmentId}/cancel`),
    onSettled: () => {
      void client.invalidateQueries({
        queryKey: [`/assessments/${assessmentId}`],
      });
    },
  });
  if (!assessment)
    return run.isPending ? (
      <p role="status">Loading assessment…</p>
    ) : (
      <ErrorMessage error={run.error} retry={run.refetch} />
    );
  return (
    <>
      <header className="page-header">
        <div>
          <Link
            className="breadcrumb"
            to={`/projects/${assessment.project_id}`}
          >
            {project.data?.name || "Project"} /
          </Link>
          <h1>
            Assessment <span className="mono">{assessment.id.slice(0, 8)}</span>
          </h1>
          <p>
            {assessment.plan_snapshot.target.name} · {date(assessment.created_at)}
          </p>
        </div>
        <div>
          <StatusBadge status={assessment.status} />
          {finished && (
            <div className="report-actions">
              <button
                type="button"
                className="subtle"
                disabled={report.isPending}
                onClick={() => report.download("json")}
              >
                Download JSON
              </button>
              <button
                type="button"
                className="subtle"
                disabled={report.isPending}
                onClick={() => report.download("html")}
              >
                Download HTML
              </button>
            </div>
          )}
        </div>
      </header>
      <ErrorMessage error={run.error} retry={run.refetch} />
      <ErrorMessage error={report.error} />
      <AssessmentSummary
        assessment={assessment}
        findingCount={results.data?.findings.length}
      />
      <section className="panel">
        <h2>Assessment request</h2>
        <dl>
          <AssessmentRequestFields assessment={assessment} targetUrl={assessment.plan_snapshot.target.url} />
          <ExecutionMetadata result={assessment.result} />
          <AssessmentSource assessment={assessment} />

        </dl>
        <ErrorMessage error={project.error} />
        {assessment.result?.error && (
          <div className="error" role="alert">
            {assessment.result.error}
          </div>
        )}
        <IncompleteExecution status={assessment.status} />
        {!finished && (
          <>
            <p role="status">
              {assessment.status === "cancelling"
                ? "Cancellation requested. Waiting for execution and cleanup."
                : "Assessment is in progress. This page updates automatically."}
            </p>
            <button
              className="danger"
              disabled={cancel.isPending || assessment.status === "cancelling"}
              onClick={() => {
                if (!cancel.isPending) cancel.mutate();
              }}
            >
              {cancel.isPending ? "Requesting…" : "Cancel assessment"}
            </button>
          </>
        )}
        <ErrorMessage error={cancel.error} />
      </section>
      {finished && <RouteResults result={assessment.result} />}
      {finished && (
        <section className="findings-section">
          <div className="section-header">
            <h2>Findings and evidence</h2>
            <button
              className="subtle"
              type="button"
              onClick={() => {
                void run.refetch();
                void results.refetch();
                if (!assessment.cleanup_pending) void evidence.refetch();
              }}
            >
              Refresh
            </button>
          </div>
          <ErrorMessage error={results.error} retry={results.refetch} />
          <ErrorMessage error={evidence.error} retry={evidence.refetch} />
          {results.isPending ? (
            <p role="status">Loading results…</p>
          ) : results.data?.findings.length === 0 ? (
            <EmptyFindings status={assessment.status} />
          ) : (
            results.data?.findings.map((finding) => (
              <FindingDetails key={finding.id} finding={finding} routes={assessment.result?.routes}>
                {evidence.isPending ? (
                  <p>Loading evidence…</p>
                ) : evidence.error ? (
                  <p>Evidence could not be retrieved. Use Try again above.</p>
                ) : (
                  <EvidenceDetails
                    evidence={evidenceByFinding.get(finding.id) ?? []}
                  />
                )}
              </FindingDetails>
            ))
          )}
        </section>
      )}
    </>
  );
}

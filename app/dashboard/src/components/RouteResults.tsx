import type { Assessment, Result } from "../api/types";
import { Fragment } from "react";
import { ResponseDetails } from "./AssessmentDetails";

export function RouteResults({ result }: { result: Result | null }) {
  if (!result) return null;
  const { routes } = result;
  return <section className="panel">
    <h2>Release decision and route coverage</h2>
    <p>Execution: {result.execution_outcome.replaceAll("_", " ")} · Cleanup: {result.cleanup_verified ? "verified" : "unverified"}</p>
    {result.cleanup_verified === false && <p role="alert">Findings and evidence are withheld until cleanup is verified.</p>}
    <p><strong>{result.verdict.status === "pass" ? "Release checks passed" : "Release blocked"}</strong>
      {" · "}Coverage {result.coverage.complete ? "complete" : "incomplete"}</p>
    {result.verdict.reasons.length ? <ul>{result.verdict.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul> : null}
    {result.partial && <p role="alert">Partial results: these findings cover only completed routes. The assessment did not complete.</p>}
    {routes.map(route => <article key={route.key}>
      <h3>{route.key} · {route.status}</h3><p>{route.url}</p>
      <p>{route.finding_count} findings · Coverage {route.coverage.complete ? "complete" : "incomplete"}</p>
      {route.response && route.response.url !== route.url && <p>Final response: {route.response.url}</p>}
      {!!route.response?.redirects.length && <p>{route.response.redirects.length} redirects followed</p>}
      {route.error && <p className="error">{route.error}</p>}
      {!route.coverage.expected_response && <p>Expected response was not received.</p>}
      {!!route.coverage.missing_checks.length && <p>Required checks not evaluated: {route.coverage.missing_checks.join(", ")}</p>}
      {route.response ? <section aria-label={routes.length === 1 ? "Response and check outcomes" : "Response and check outcomes: " + route.key}>
        <h4>Response and check outcomes</h4>
        <ResponseDetails response={route.response} plugins={route.plugins} />
      </section> : <p>No complete response</p>}
    </article>)}
    {result.comparison?.status === "available" && <p>Baseline comparison: {result.comparison.new?.length ?? 0} new,
      {" "}{result.comparison.resolved?.length ?? 0} resolved, {result.comparison.unchanged?.length ?? 0} unchanged findings.</p>}
    {result.comparison?.status === "unavailable" && <p>Baseline comparison unavailable: {result.comparison.reason}</p>}
  </section>;
}

export function AssessmentSource({ assessment }: { assessment: Assessment }) {
  const plan = assessment.plan_snapshot;
  return <><dt>Assessment source</dt><dd>{plan.target.kind === "website" ? "Existing website" : "Isolated Docker bundle"}</dd>
    {Object.entries(plan.images).map(([name, image]) => <Fragment key={name}><dt>{name} image</dt><dd>{image}</dd></Fragment>)}
  </>;
}

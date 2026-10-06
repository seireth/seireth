import { useState } from "react";
import { Link, useParams } from "react-router";
import { useList, useResource } from "../api/queries";
import type { Assessment, Audit, Project, Target } from "../api/types";
import {
  date,
  Empty,
  ErrorMessage,
  More,
  StatusBadge,
} from "../components/common";
import TargetForm from "../components/TargetForm";

export default function ProjectPage() {
  const { projectId = "" } = useParams();
  const [tab, setTab] = useState("assessments");
  const project = useResource<Project>(`/projects/${projectId}`);
  const targets = useList<Target>(`/projects/${projectId}/targets`);
  const assessments = useList<Assessment>(
    `/projects/${projectId}/assessments`,
    tab === "assessments",
  );
  const audit = useResource<Audit[]>(
    `/projects/${projectId}/audit-events`,
    tab === "audit",
  );
  const targetItems = targets.data?.pages.flatMap((p) => p.items) ?? [];
  const runs = assessments.data?.pages.flatMap((p) => p.items) ?? [];
  if (project.isPending) return <p role="status">Loading project…</p>;
  if (!project.data)
    return (
      <ErrorMessage
        error={project.error}
        retry={() => {
          void project.refetch();
        }}
      />
    );
  return (
    <>
      <header className="page-header">
        <div>
          <Link className="breadcrumb" to="/">
            Projects /
          </Link>
          <h1>{project.data.name}</h1>
          <p>Created {date(project.data.created_at)}</p>
        </div>
        <Link className="button" to={`/projects/${projectId}/new`}>
          New assessment
        </Link>
      </header>
      <nav className="tabs" aria-label="Project sections">
        {["assessments", "targets", "audit"].map((t) => (
          <button
            className={tab === t ? "active" : "subtle"}
            type="button"
            key={t}
            aria-current={tab === t ? "page" : undefined}
            onClick={() => setTab(t)}
          >
            {t === "audit" ? "Audit trail" : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>
      {tab === "assessments" && (
        <section className="panel">
          <h2>Assessment history</h2>
          <ErrorMessage
            error={assessments.error}
            retry={() => {
              void assessments.refetch();
            }}
          />
          {assessments.isPending ? (
            <p role="status">Loading history…</p>
          ) : !runs.length && !assessments.error ? (
            <Empty>
              No assessments yet. Register a target and choose your checks to begin.
            </Empty>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Assessment</th>
                    <th>Target</th>
                    <th>Assessment URL</th>
                    <th>Status</th>
                    <th>Cleanup</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((a) => (
                    <tr key={a.id}>
                      <td>
                        <Link to={`/assessments/${a.id}`}>
                          {a.id.slice(0, 8)}
                        </Link>
                        <small>{a.plugins.join(", ")}</small>
                      </td>
                      <td>
                        {targetItems.find((t) => t.id === a.target_id)?.name ||
                          a.target_id.slice(0, 8)}
                      </td>
                      <td>{a.url}</td>
                      <td>
                        <StatusBadge status={a.status} />
                      </td>
                      <td>
                        {a.cleanup_pending
                          ? "Pending"
                          : a.result?.cleanup_verified
                            ? "Verified"
                            : "No outcome yet"}
                      </td>
                      <td>{date(a.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <More query={assessments} />
        </section>
      )}
      {tab === "targets" && (
        <>
          <section className="panel">
            <h2>Register a target</h2>
            <TargetForm key={projectId} projectId={projectId} />
          </section>
          <section className="panel">
            <h2>Registered targets</h2>
            <ErrorMessage
              error={targets.error}
              retry={() => {
                void targets.refetch();
              }}
            />
            {targets.isPending && <p role="status">Loading targets…</p>}
            {targets.isSuccess && !targetItems.length && (
              <Empty>No targets registered.</Empty>
            )}
            {targetItems.map((t) => (
              <article className="record" key={t.id}>
                <h3>{t.name}</h3>
                <p>{t.url}</p>
                <code>{t.image}</code>
              </article>
            ))}
            <More query={targets} />
          </section>
        </>
      )}
      {tab === "audit" && (
        <section className="panel">
          <h2>Audit trail</h2>
          <ErrorMessage
            error={audit.error}
            retry={() => {
              void audit.refetch();
            }}
          />
          {audit.isPending ? (
            <p role="status">Loading audit trail…</p>
          ) : (
            audit.data?.map((event) => (
              <article className="audit-event" key={event.id}>
                <span className="dot" />
                <div>
                  <strong>{event.action}</strong>
                  <small>
                    {date(event.created_at)} · {event.resource_id}
                  </small>
                  {Object.keys(event.details).length > 0 && (
                    <pre>{JSON.stringify(event.details, null, 2)}</pre>
                  )}
                </div>
              </article>
            ))
          )}
        </section>
      )}
    </>
  );
}

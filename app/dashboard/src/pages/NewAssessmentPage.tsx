import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../api/client";
import { useList, useResource } from "../api/queries";
import type {
  Assessment,
  Plugin,
  Project,
  Runtime,
  Target,
} from "../api/types";
import { ErrorMessage, FieldError, More } from "../components/common";
import TargetForm from "../components/TargetForm";

export default function NewAssessmentPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [targetId, setTargetId] = useState("");
  const [url, setUrl] = useState<string | null>(null);
  const [selectedPlugins, setPlugins] = useState<string[]>([]);
  const [newTarget, setNewTarget] = useState(false);
  const project = useResource<Project>(`/projects/${projectId}`);
  const runtime = useResource<Runtime>("/runtime");
  const plugins = useResource<Plugin[]>("/plugins");
  const targets = useList<Target>(`/projects/${projectId}/targets`);
  const target = useResource<Target>(`/targets/${targetId}`, !!targetId);
  const assessmentUrl = url ?? target.data?.url ?? "";
  const targetItems = targets.data?.pages.flatMap((p) => p.items) ?? [];
  if (target.data && !targetItems.some((item) => item.id === target.data.id))
    targetItems.push(target.data);
  const create = useMutation({
    mutationFn: () =>
      post<Assessment>("/assessments", {
        project_id: projectId,
        target_id: targetId,
        url: assessmentUrl,
        plugins: selectedPlugins,
      }),
    onSuccess: (a) => {
      void client.invalidateQueries({
        queryKey: [`/projects/${projectId}/assessments`],
      });
      navigate(`/assessments/${a.id}`);
    },
  });
  return (
    <>
      <header className="page-header">
        <div>
          <Link className="breadcrumb" to={`/projects/${projectId}`}>
            {project.data?.name || "Project"} /
          </Link>
          <h1>New assessment</h1>
          <p>
            Choose a target, response URL, and checks.
          </p>
        </div>
        <span className="badge neutral">
          {runtime.data?.sandbox_backend === "inmemory"
            ? "Simulated responses"
            : runtime.data?.sandbox_backend === "docker"
              ? "Docker assessment"
              : "Backend unavailable"}
        </span>
      </header>
      <ErrorMessage error={project.error} />
      <ErrorMessage error={runtime.error} retry={runtime.refetch} />
      <section className="panel step">
        <span className="step-number">01</span>
        <h2>Target</h2>
        <label>
          Registered target
          <select
            value={targetId}
            onChange={(e) => {
              setTargetId(e.target.value);
              setUrl(null);
            }}
          >
            <option value="">Select a target</option>
            {targetItems.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} · {t.url}
              </option>
            ))}
          </select>
          <FieldError error={create.error} name="target_id" />
        </label>
        <ErrorMessage error={targets.error} retry={targets.refetch} />
        <ErrorMessage error={target.error} />
        <More query={targets} />
        <button
          type="button"
          className="subtle"
          onClick={() => setNewTarget(!newTarget)}
        >
          {newTarget ? "Close registration" : "Register a new target"}
        </button>
        {newTarget && (
          <TargetForm
            projectId={projectId}
            onCreated={(id) => {
              setTargetId(id);
              setUrl(null);
              setNewTarget(false);
            }}
          />
        )}
        {target.data && (
          <p className="hint">
            {target.data.url} · {target.data.image}
          </p>
        )}
      </section>
      <section className="panel step">
        <span className="step-number">02</span>
        <h2>Response</h2>
        <label>
          Assessment URL
          <input required type="url" disabled={!target.data}
            value={assessmentUrl}
            onChange={(e) => setUrl(e.target.value)} />
          <FieldError error={create.error} name="url" />
        </label>
        <p className="hint">Choose one response within the registered target's origin and path.</p>
      </section>
      <section className="panel step">
        <span className="step-number">03</span>
        <h2>Checks</h2>
        <ErrorMessage error={plugins.error} retry={plugins.refetch} />
        <fieldset className="plugin-grid">
          <legend>Select at least one plugin</legend>
          {plugins.data?.map((plugin) => (
            <label className="plugin-choice" key={plugin.id}>
              <input
                type="checkbox"
                checked={selectedPlugins.includes(plugin.id)}
                onChange={(e) =>
                  setPlugins(
                    e.target.checked
                      ? [...selectedPlugins, plugin.id]
                      : selectedPlugins.filter((p) => p !== plugin.id),
                  )
                }
              />
              <span>
                {plugin.name}
                <small>{plugin.description}</small>
              </span>
            </label>
          ))}
        </fieldset>
        <FieldError error={create.error} name="plugins" />
      </section>
      <section className="submit-bar">
        <p>
          The API rechecks the target boundary before executing. Checks analyze one
          response.
        </p>
        <ErrorMessage error={create.error} />
        <button
          disabled={
            create.isPending ||
            !target.data ||
            !assessmentUrl.trim() ||
            !selectedPlugins.length ||
            !runtime.data ||
            !project.data
          }
          onClick={() => {
            if (!create.isPending) create.mutate();
          }}
        >
          {create.isPending ? "Submitting…" : "Run assessment"}
        </button>
      </section>
    </>
  );
}

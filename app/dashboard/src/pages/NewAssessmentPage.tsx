import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../api/client";
import { useList, useResource } from "../api/queries";
import type {
  Assessment,
  Plugin,
  Project,
  Profiles,
  Target,
} from "../api/types";
import { ErrorMessage, FieldError, More } from "../components/common";
import TargetForm from "../components/TargetForm";
import { RoutePlanEditor, newRoute, routeRequest, selectRoutePlugins } from "../components/RoutePlanEditor";
import type { RouteDraft } from "../components/RoutePlanEditor";

export default function NewAssessmentPage() {
  const { projectId = "" } = useParams();
  return <AssessmentForm key={projectId} projectId={projectId} />;
}

function AssessmentForm({ projectId }: { projectId: string }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [targetId, setTargetId] = useState("");
  const [url, setUrl] = useState<string | null>(null);
  const [selectedPlugins, setPlugins] = useState<string[]>([]);
  const [newTarget, setNewTarget] = useState(false);
  const [usePlan, setUsePlan] = useState(false);
  const [routes, setRoutes] = useState<RouteDraft[]>([]);
  const [baseline, setBaseline] = useState("");
  const selectTarget = (id: string) => {
    setTargetId(id);
    setUrl(null);
    setUsePlan(false);
    setRoutes([]);
  };
  const profiles = useResource<Profiles>("/runtime/profiles");
  const history = useList<Assessment>("/projects/" + projectId + "/assessments");
  const project = useResource<Project>(`/projects/${projectId}`);
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
        ...(usePlan ? { routes: routes.map(route => routeRequest(route, selectedPlugins)), baseline: baseline || null }
          : { url: assessmentUrl, plugins: selectedPlugins }),
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
          {target.data ? target.data.kind === "website" ? "Website assessment" : "Docker assessment" : "Select a target"}
        </span>
      </header>
      <ErrorMessage error={project.error} />
      <section className="panel step">
        <span className="step-number">01</span>
        <h2>Target</h2>
        <label>
          Registered target
          <select
            value={targetId}
            onChange={(e) => selectTarget(e.target.value)}
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
              selectTarget(id);
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
        <label><input type="checkbox" checked={usePlan} onChange={e => {
          setUsePlan(e.target.checked); if (!routes.length) setRoutes([newRoute(assessmentUrl)]);
        }} />Use a route plan with response expectations</label>
        {!usePlan && <label>
          Assessment URL
          <input required type="url" disabled={!target.data}
            value={assessmentUrl}
            onChange={(e) => setUrl(e.target.value)} />
          <FieldError error={create.error} name="url" />
        </label>}
        <p className="hint">Responses must stay within the registered target's origin and path.</p>
      </section>
      {usePlan && <RoutePlanEditor routes={routes} onChange={setRoutes} profiles={profiles.data} plugins={plugins.data} selectedPlugins={selectedPlugins} />}
      {usePlan && <label>Baseline assessment<select value={baseline} onChange={e => setBaseline(e.target.value)}>
        <option value="">No comparison</option>{history.data?.pages.flatMap(page => page.items).filter(item => item.status === "completed")
          .map(item => <option key={item.id} value={item.id}>{item.id.slice(0, 8)} · {item.created_at}</option>)}
      </select></label>}
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
                onChange={(e) => {
                  const chosen = e.target.checked ? [...selectedPlugins, plugin.id] : selectedPlugins.filter(p => p !== plugin.id);
                  setPlugins(chosen);
                  setRoutes(current => current.map(route => route.plugins === undefined ? selectRoutePlugins(route, chosen, true) : route));
                }}
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
          The API rechecks the target boundary and evaluates the declared responses.
        </p>
        <ErrorMessage error={create.error} />
        <button
          disabled={
            create.isPending ||
            !target.data ||
            (usePlan ? !routes.length || routes.some(route => !route.url.trim() || !(route.plugins ?? selectedPlugins).length)
              : !assessmentUrl.trim() || !selectedPlugins.length) ||

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

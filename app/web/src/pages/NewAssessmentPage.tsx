import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../api/client";
import { useList, useResource } from "../api/queries";
import type {
  Assessment,
  Plugin,
  Project,
  Runtime,
  Scope,
  Target,
} from "../api/types";
import { date, ErrorMessage, FieldError, More } from "../components/common";
import TargetForm from "../components/TargetForm";
import ScopeForm from "../components/ScopeForm";

export default function NewAssessmentPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [targetId, setTargetId] = useState("");
  const [scopeId, setScopeId] = useState("");
  const [selectedPlugins, setPlugins] = useState<string[]>([]);
  const [newTarget, setNewTarget] = useState(false);
  const [newScope, setNewScope] = useState(false);
  const project = useResource<Project>(`/projects/${projectId}`);
  const runtime = useResource<Runtime>("/runtime");
  const plugins = useResource<Plugin[]>("/plugins");
  const targets = useList<Target>(`/projects/${projectId}/targets`);
  const scopes = useList<Scope>(
    `/projects/${projectId}/authorization-scopes?target_id=${encodeURIComponent(targetId)}`,
    !!targetId,
  );
  const target = useResource<Target>(`/targets/${targetId}`, !!targetId);
  const targetItems = targets.data?.pages.flatMap((p) => p.items) ?? [];
  if (target.data && !targetItems.some((item) => item.id === target.data.id))
    targetItems.push(target.data);
  const scopeItems = scopes.data?.pages.flatMap((p) => p.items) ?? [];
  const selectedScope = useResource<Scope>(
    `/authorization-scopes/${scopeId}`,
    !!scopeId,
  );
  if (
    selectedScope.data &&
    !scopeItems.some((item) => item.id === selectedScope.data.id)
  )
    scopeItems.push(selectedScope.data);
  const [clock, setClock] = useState(Date.now);
  const expiresAt = selectedScope.data?.expires_at;
  useEffect(() => {
    if (!expiresAt) return;
    const remaining = new Date(expiresAt).getTime() - Date.now();
    if (remaining <= 0) return;
    const timer = window.setTimeout(
      () => setClock(Date.now()),
      Math.min(remaining + 1, 86_400_000),
    );
    return () => window.clearTimeout(timer);
  }, [expiresAt, clock]);
  const validScope =
    selectedScope.data?.target_id === targetId &&
    selectedScope.data.project_id === projectId &&
    new Date(selectedScope.data.expires_at).getTime() > Date.now();
  const create = useMutation({
    mutationFn: () =>
      post<Assessment>("/assessments", {
        project_id: projectId,
        target_id: targetId,
        scope_id: scopeId,
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
            Choose an owned target, authorize its URL, and select your checks.
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
      <ErrorMessage
        error={runtime.error}
        retry={() => {
          void runtime.refetch();
        }}
      />
      <section className="panel step">
        <span className="step-number">01</span>
        <h2>Target</h2>
        <label>
          Registered target
          <select
            value={targetId}
            onChange={(e) => {
              setTargetId(e.target.value);
              setScopeId("");
              setNewScope(false);
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
        <ErrorMessage
          error={targets.error}
          retry={() => {
            void targets.refetch();
          }}
        />
        <ErrorMessage error={target.error} />
        <More
          hasMore={targets.hasNextPage}
          loading={targets.isFetchingNextPage}
          load={() => {
            void targets.fetchNextPage();
          }}
        />
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
              setScopeId("");
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
        <h2>Authorization scope</h2>
        <label>
          Authorized scope
          <select
            disabled={!targetId}
            value={scopeId}
            onChange={(e) => setScopeId(e.target.value)}
          >
            <option value="">Select a scope</option>
            {scopeItems.map((s) => {
              const expired = new Date(s.expires_at).getTime() <= Date.now();
              return (
                <option key={s.id} value={s.id} disabled={expired}>
                  {s.allowed_url} · {expired ? "Expired" : "Expires"}{" "}
                  {date(s.expires_at)}
                </option>
              );
            })}
          </select>
        </label>
        <ErrorMessage
          error={scopes.error}
          retry={() => {
            void scopes.refetch();
          }}
        />
        <FieldError error={create.error} name="scope_id" />
        <ErrorMessage error={selectedScope.error} />
        <More
          hasMore={scopes.hasNextPage}
          loading={scopes.isFetchingNextPage}
          load={() => {
            void scopes.fetchNextPage();
          }}
        />
        <button
          type="button"
          className="subtle"
          disabled={!target.data}
          onClick={() => setNewScope(!newScope)}
        >
          {newScope ? "Close authorization" : "Create a new scope"}
        </button>
        {newScope && target.data && (
          <ScopeForm
            key={targetId}
            target={target.data}
            onCreated={(id) => {
              setScopeId(id);
              setNewScope(false);
            }}
          />
        )}
      </section>
      <section className="panel step">
        <span className="step-number">03</span>
        <h2>Checks</h2>
        <ErrorMessage
          error={plugins.error}
          retry={() => {
            void plugins.refetch();
          }}
        />
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
                <strong>{plugin.name}</strong>
                <small>{plugin.description}</small>
              </span>
            </label>
          ))}
        </fieldset>
        <FieldError error={create.error} name="plugins" />
      </section>
      <section className="submit-bar">
        <p>
          The API rechecks authorization before executing. Checks analyze one
          response.
        </p>
        <ErrorMessage error={create.error} />
        <button
          disabled={
            create.isPending ||
            !validScope ||
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

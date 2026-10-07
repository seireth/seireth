import { useState } from "react";
import { Link } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { post } from "../api/client";
import { useList } from "../api/queries";
import type { Project } from "../api/types";
import {
  date,
  Empty,
  ErrorMessage,
  FieldError,
  More,
} from "../components/common";

export default function ProjectsPage() {
  const [name, setName] = useState("");
  const client = useQueryClient();
  const projects = useList<Project>("/projects");
  const create = useMutation({
    mutationFn: () => post<{ id: string }>("/projects", { name: name.trim() }),
    onSuccess: () => {
      setName("");
      void client.invalidateQueries({ queryKey: ["/projects"] });
    },
  });
  const items = projects.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Projects</h1>
          <p>Organize targets, authorization, and assessment history.</p>
        </div>
        <span className="badge neutral">Local · single operator</span>
      </header>
      <section className="panel">
        <h2>Create a project</h2>
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!create.isPending) create.mutate();
          }}
        >
          <label>
            Project name
            <input
              required
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Customer portal"
            />
            <FieldError error={create.error} name="name" />
          </label>
          <button type="submit" disabled={create.isPending || !name.trim()}>
            {create.isPending ? "Creating…" : "Create project"}
          </button>
        </form>
        <ErrorMessage error={create.error} />
      </section>
      <section className="section-header">
        <h2>Your projects</h2>
        <span>{items.length} loaded</span>
      </section>
      <ErrorMessage error={projects.error} retry={projects.refetch} />
      {projects.isPending ? (
        <p role="status">Loading projects…</p>
      ) : !items.length && !projects.error ? (
        <Empty>
          Create your first project to register a target and run an assessment.
        </Empty>
      ) : (
        <div className="project-grid">
          {items.map((p) => (
            <Link className="project-card" key={p.id} to={`/projects/${p.id}`}>
              <span className="project-icon">◇</span>
              <h3>{p.name}</h3>
              <p>Created {date(p.created_at)}</p>
              <span className="card-action">Open project →</span>
            </Link>
          ))}
        </div>
      )}
      <More query={projects} />
    </>
  );
}

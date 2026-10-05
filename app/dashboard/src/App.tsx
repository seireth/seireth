import { Link, NavLink, Route, Routes } from "react-router";
import { useList, useResource } from "./api/queries";
import type { Project, Runtime } from "./api/types";
import { ErrorMessage, More } from "./components/common";
import ProjectsPage from "./pages/ProjectsPage";
import ProjectPage from "./pages/ProjectPage";
import NewAssessmentPage from "./pages/NewAssessmentPage";
import AssessmentPage from "./pages/AssessmentPage";
import logo from "../../../docs/assets/seireth-logo.png";

export default function App() {
  const projects = useList<Project>("/projects");
  const runtime = useResource<Runtime>("/runtime");
  return (
    <div className="workspace">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link to="/" className="brand">
          <img src={logo} alt="" />
          <span>
            SEIRETH<small>Assessment workspace</small>
          </span>
        </Link>
        <div className="operator">
          <span className="dot" />
          Local operator
        </div>
        <NavLink to="/" end className="nav-link">
          All projects
        </NavLink>
        <h2 className="nav-title">Projects</h2>
        <nav aria-label="Project navigation">
          {projects.data?.pages
            .flatMap((p) => p.items)
            .map((p) => (
              <NavLink className="nav-link" to={`/projects/${p.id}`} key={p.id}>
                {p.name}
              </NavLink>
            ))}
        </nav>
        <ErrorMessage
          error={projects.error}
          retry={() => {
            void projects.refetch();
          }}
        />
        <More
          hasMore={projects.hasNextPage}
          loading={projects.isFetchingNextPage}
          load={() => {
            void projects.fetchNextPage();
          }}
        />
        <div className="sidebar-footer">
          <span className="eyebrow">Execution backend</span>
          <strong>
            {runtime.data?.sandbox_backend === "inmemory"
              ? "Simulated responses"
              : runtime.data?.sandbox_backend === "docker"
                ? "Docker containers"
                : "Unavailable"}
          </strong>
          <p>
            Owned targets. Scoped checks.
            <br />
            Verified cleanup.
          </p>
        </div>
      </aside>
      <main id="main" tabIndex={-1}>
        <Routes>
          <Route index element={<ProjectsPage />} />
          <Route path="projects/:projectId" element={<ProjectPage />} />
          <Route
            path="projects/:projectId/new"
            element={<NewAssessmentPage />}
          />
          <Route
            path="assessments/:assessmentId"
            element={<AssessmentPage />}
          />
          <Route
            path="*"
            element={
              <>
                <h1>Page not found</h1>
                <Link to="/">Return to projects</Link>
              </>
            }
          />
        </Routes>
      </main>
    </div>
  );
}

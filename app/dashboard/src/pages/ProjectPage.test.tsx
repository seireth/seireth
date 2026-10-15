import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, MemoryRouter, Route, Routes } from "react-router";
import { expect, it, vi } from "vitest";
import ProjectPage from "./ProjectPage";

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
function show(fetcher: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  for (const id of ["p", "q"])
    client.setQueryData([`/projects/${id}`], {
      id,
      name: `Project ${id}`,
      created_at: new Date().toISOString(),
    });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects/p"]}>
        <Link to="/projects/q">Switch to project q</Link>
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function metadata(path: string) {
  return json(
    path.endsWith("/target-images") ? { items: [{image: "demo", id: "sha256:abc"}]} : { items: [], has_more: false },
  );
}

it("clears the target draft when switching between cached projects", async () => {
  show(vi.fn(async (url: string) => metadata(url)));
  await userEvent.click(screen.getByRole("button", { name: "Targets" }));
  await screen.findByLabelText("Docker image");
  await userEvent.type(screen.getByLabelText("Target name"), "Unfinished target");
  await userEvent.type(screen.getByLabelText("Registered URL"), "https://p.test/");
  await userEvent.click(screen.getByRole("link", { name: "Switch to project q" }));
  expect(await screen.findByRole("heading", { name: "Project q" })).toBeVisible();
  expect(screen.getByLabelText("Target name")).toHaveValue("");
  expect(screen.getByLabelText("Registered URL")).toHaveValue("");
  expect(screen.getByRole("button", { name: "Register target" })).toBeDisabled();
});

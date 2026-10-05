import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, MemoryRouter, Route, Routes } from "react-router";
import { expect, it, vi } from "vitest";
import ProjectPage from "./ProjectPage";

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });
const runtime = {
  sandbox_backend: "inmemory",
  default_target_image: "demo",
  allowed_target_images: ["demo"],
};

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
    path.endsWith("/runtime") ? runtime : { items: [], has_more: false },
  );
}

it.each([
  ["Targets", "/targets?", "Loading targets…", "No targets registered."],
  [
    "Scopes",
    "/authorization-scopes?",
    "Loading scopes…",
    "No authorization scopes.",
  ],
])("distinguishes loading, failed, and empty %s requests", async (tab, path, loading, empty) => {
  let resolveRead: ((response: Response) => void) | undefined;
  let retry = false;
  show(
    vi.fn(async (url: string) => {
      if (!url.includes(path)) return metadata(url);
      if (retry) return json({ items: [], has_more: false });
      return new Promise<Response>((resolve) => {
        resolveRead = resolve;
      });
    }),
  );
  await userEvent.click(screen.getByRole("button", { name: tab }));
  expect(screen.getByRole("status")).toHaveTextContent(loading);
  expect(screen.queryByText(empty)).toBeNull();
  await waitFor(() => expect(resolveRead).toBeDefined());
  resolveRead!(json({ detail: "read failed" }, 500));
  expect(await screen.findByRole("alert")).toHaveTextContent("read failed");
  expect(screen.queryByText(empty)).toBeNull();
  expect(screen.queryByRole("status")).toBeNull();

  retry = true;
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText(empty)).toBeVisible();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("clears the target draft when switching between cached projects", async () => {
  show(vi.fn(async (url: string) => metadata(url)));
  await userEvent.click(screen.getByRole("button", { name: "Targets" }));
  await screen.findByRole("option", { name: "demo" });
  await userEvent.type(screen.getByLabelText("Target name"), "Unfinished target");
  await userEvent.type(screen.getByLabelText("Registered URL"), "https://p.test/");
  await userEvent.click(screen.getByRole("link", { name: "Switch to project q" }));
  expect(await screen.findByRole("heading", { name: "Project q" })).toBeVisible();
  expect(screen.getByLabelText("Target name")).toHaveValue("");
  expect(screen.getByLabelText("Registered URL")).toHaveValue("");
  expect(screen.getByRole("button", { name: "Register target" })).toBeDisabled();
});

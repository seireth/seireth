import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { expect, it, vi } from "vitest";
import NewAssessmentPage from "./NewAssessmentPage";

it("uses the catalog and target URL, blocks duplicate submissions, and preserves selection on failure", async () => {
  let rejectWrite: ((response: Response) => void) | undefined;
  const target = {
    id: "t",
    project_id: "p",
    name: "Demo",
    image: "allowed",
    url: "http://demo.test/",
  };
  const json = (data: unknown) => new Response(JSON.stringify(data));
  const fetcher = vi.fn((path: string, options?: RequestInit) => {
    if (options?.method === "POST")
      return new Promise<Response>((resolve) => {
        rejectWrite = resolve;
      });
    if (path.endsWith("/runtime"))
      return Promise.resolve(
        json({
          sandbox_backend: "inmemory",
        }),
      );
    if (path.endsWith("/plugins"))
      return Promise.resolve(
        json([
          {
            id: "catalog-check",
            name: "Catalog supplied check",
            description: "Passive observation",
          },
        ]),
      );
    if (path.includes("/targets?"))
      return Promise.resolve(json({ items: [target], has_more: false }));
    if (path.endsWith("/targets/t")) return Promise.resolve(json(target));
    return Promise.resolve(
      json({ id: "p", name: "Project", created_at: new Date().toISOString() }),
    );
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects/p/new"]}>
        <Routes>
          <Route
            path="/projects/:projectId/new"
            element={<NewAssessmentPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  expect(screen.getByRole("button", { name: "Run assessment" })).toBeDisabled();
  await screen.findByRole("option", { name: /Demo/ });
  await user.selectOptions(screen.getByLabelText("Registered target"), "t");
  await waitFor(() => expect(screen.getByLabelText("Assessment URL")).toHaveValue(target.url));
  await user.clear(screen.getByLabelText("Assessment URL"));
  await user.type(screen.getByLabelText("Assessment URL"), target.url + "cookies");
  await user.click(
    await screen.findByRole("checkbox", { name: /Catalog supplied check/ }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Run assessment" }),
    ).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "Run assessment" }));
  expect(screen.getByRole("button", { name: "Submitting…" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Submitting…" }));
  const writes = fetcher.mock.calls.filter(
    ([, options]) => options?.method === "POST",
  );
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0][1]?.body))).toEqual({
    project_id: "p",
    target_id: "t",
    url: target.url + "cookies",
    plugins: ["catalog-check"],
  });
  rejectWrite!(
    new Response(JSON.stringify({ detail: "URL outside target" }), { status: 403 }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("URL outside target");
  expect(screen.getByLabelText("Assessment URL")).toHaveValue(target.url + "cookies");
  expect(
    screen.getByRole("checkbox", { name: /Catalog supplied check/ }),
  ).toBeChecked();
});

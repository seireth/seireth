import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { expect, it, vi } from "vitest";
import NewAssessmentPage from "./NewAssessmentPage";

it("uses the catalog and valid scope, blocks duplicate submissions, and preserves selection on failure", async () => {
  let rejectWrite: ((response: Response) => void) | undefined;
  const target = {
    id: "t",
    project_id: "p",
    name: "Demo",
    image: "allowed",
    url: "http://demo.test/",
  };
  const scopes = [
    {
      id: "s",
      target_id: "t",
      project_id: "p",
      allowed_url: target.url,
      expires_at: new Date(Date.now() + 60_000).toISOString(),
    },
    {
      id: "old",
      target_id: "t",
      project_id: "p",
      allowed_url: target.url,
      expires_at: new Date(0).toISOString(),
    },
  ];
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
          default_target_image: "allowed",
          allowed_target_images: ["allowed"],
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
    if (path.includes("/authorization-scopes?"))
      return Promise.resolve(json({ items: scopes, has_more: false }));
    if (path.endsWith("/authorization-scopes/s"))
      return Promise.resolve(json(scopes[0]));
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
  expect(await screen.findByRole("option", { name: /Expired/ })).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Authorized scope"), "s");
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
    scope_id: "s",
    plugins: ["catalog-check"],
  });
  rejectWrite!(
    new Response(JSON.stringify({ detail: "scope expired" }), { status: 403 }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("scope expired");
  expect(screen.getByLabelText("Authorized scope")).toHaveValue("s");
  expect(
    screen.getByRole("checkbox", { name: /Catalog supplied check/ }),
  ).toBeChecked();
});

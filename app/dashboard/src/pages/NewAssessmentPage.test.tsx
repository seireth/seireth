import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { expect, it, vi } from "vitest";
import NewAssessmentPage from "./NewAssessmentPage";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/projects/p/assessments/new"]}>
    <Routes><Route path="/projects/:projectId/assessments/new" element={<NewAssessmentPage />} />
      <Route path="/assessments/:id" element={<p>Assessment submitted</p>} /></Routes>
  </MemoryRouter></QueryClientProvider>);
}

function show() {
  const targets = {
    t: { id: "t", project_id: "p", name: "Original", kind: "website", image: null, url: "https://original.test/" },
    created: { id: "created", project_id: "p", name: "New", kind: "website", image: null, url: "https://new.test/" },
  };
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
    let data: unknown;
    if (options?.method === "POST") data = { id: path.endsWith("/targets") ? "created" : "assessment" };
    else if (path.endsWith("/runtime/profiles")) data = { requests: {}, launches: {}, networks: {}, trusts: [] };
    else if (path.endsWith("/plugins")) data = [{ id: "http-security-headers", name: "HTTP security headers", description: "Inspect response protections." }];
    else if (path.endsWith("/plugin-rules")) data = {};
    else if (path.endsWith("/projects/p")) data = { id: "p", name: "Project" };
    else if (path.includes("/projects/p/targets?")) data = { items: [targets.t], has_more: false };
    else if (path.includes("/assessments?")) data = { items: [], has_more: false };
    else if (path.endsWith("/targets/t")) data = targets.t;
    else if (path.endsWith("/targets/created")) data = targets.created;
    else if (path.endsWith("/target-images")) data = { items: [] };
    else throw new Error("Unexpected request: " + path);
    return new Response(JSON.stringify(data));
  });
  vi.stubGlobal("fetch", fetcher);
  renderPage();
  return fetcher;
}

it("submits route-specific plugins without requiring a global selection", async () => {
  const fetcher = show();
  const user = userEvent.setup();
  await screen.findByRole("option", { name: /Original/ });
  await user.selectOptions(screen.getByLabelText("Registered target"), "t");
  await waitFor(() => expect(screen.getByLabelText("Assessment URL")).toHaveValue("https://original.test/"));
  await user.click(screen.getByRole("checkbox", { name: /Use a route plan/ }));
  const route = within(screen.getByRole("group", { name: "Route 1" }));
  await user.click(route.getByText("Route checks"));
  await user.click(route.getByRole("checkbox", { name: "HTTP security headers" }));
  const submit = screen.getByRole("button", { name: "Run assessment" });
  expect(submit).toBeEnabled();
  await user.click(submit);
  await screen.findByText("Assessment submitted");
  const request = fetcher.mock.calls.find(([path, options]) => path.endsWith("/assessments") && options?.method === "POST");
  const body = JSON.parse(String(request?.[1]?.body));
  expect(body.routes[0].plugins).toEqual(["http-security-headers"]);
  expect(body).not.toHaveProperty("plugins");
});

it("clears the previous route plan when a new target is registered", async () => {
  show();
  const user = userEvent.setup();
  await screen.findByRole("option", { name: /Original/ });
  await user.selectOptions(screen.getByLabelText("Registered target"), "t");
  await user.click(screen.getByRole("checkbox", { name: /Use a route plan/ }));
  await user.click(screen.getByRole("button", { name: "Register a new target" }));
  await user.selectOptions(screen.getByLabelText("Assessment source"), "website");
  await user.type(screen.getByLabelText("Target name"), "New");
  await user.type(screen.getByLabelText("Registered URL"), "https://new.test/");
  await user.click(screen.getByRole("button", { name: "Register target" }));
  await waitFor(() => expect(screen.getByLabelText("Assessment URL")).toHaveValue("https://new.test/"));
  expect(screen.getByRole("checkbox", { name: /Use a route plan/ })).not.toBeChecked();
  expect(screen.queryByRole("group", { name: "Route 1" })).not.toBeInTheDocument();
});

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
  renderPage();
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

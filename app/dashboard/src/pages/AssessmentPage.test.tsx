import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { expect, it, vi } from "vitest";
import type { Assessment, Status } from "../api/types";
import AssessmentPage from "./AssessmentPage";

const assessment = (status: Status, cleanup_pending = false): Assessment => ({
  id: "a",
  project_id: "p",
  target_id: "t",
  url: "http://demo.test/",
  created_at: new Date().toISOString(),
  plugins: ["cookie-security"],
  status,
  cleanup_pending,
  result: {
    cleanup_verified: !cleanup_pending,
    sandbox_backend: "docker",
    plugins: [{ id: "cookie-security", finding_count: 1 }],
  },
});
const finding = {
  id: "f",
  plugin: "cookie-security",
  title: "SameSite configuration",
  severity: "low",
  description: "<script>synthetic</script>",
  remediation: "Set Secure.",
};
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });

function show(fetcher: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/assessments/a"]}>
        <Routes>
          <Route
            path="/assessments/:assessmentId"
            element={<AssessmentPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, ...view };
}
function metadata(path: string) {
  if (path.includes("/projects/"))
    return { id: "p", name: "Project", created_at: new Date().toISOString() };
  if (path.includes("/targets/"))
    return {
      id: "t",
      name: "Demo",
      url: "http://demo.test/",
      project_id: "p",
      image: "demo",
    };
  throw new Error(`Unexpected metadata request: ${path}`);
}

it("keeps findings when evidence fails and retries evidence independently", async () => {
  let evidenceCalls = 0;
  const fetcher = vi.fn(async (path: string) => {
    if (path.endsWith("/evidence")) {
      evidenceCalls++;
      return evidenceCalls === 1
        ? json({ detail: "stored evidence is invalid" }, 500)
        : json({
            evidence: [
              {
                id: "e",
                finding_id: "f",
                kind: "http-response",
                data: {
                  url: "http://demo.test/",
                  header: "set-cookie",
                  cookie_name: "original",
                  rule: "samesite-none-without-secure",
                  samesite: "none",
                  secure: false,
                },
              },
            ],
          });
    }
    if (path.endsWith("/results")) return json({ findings: [finding] });
    return json(
      path.endsWith("/assessments/a")
        ? assessment("completed")
        : metadata(path),
    );
  });
  show(fetcher);
  expect(
    await screen.findByRole("heading", { name: finding.title }),
  ).toBeVisible();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "stored evidence is invalid",
  );
  expect(screen.getByText(finding.description)).toBeVisible();
  expect(document.querySelector("script")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await userEvent.click(screen.getByText("Evidence", { selector: "summary" }));
  expect(await screen.findByText("original")).toBeVisible();
  expect(evidenceCalls).toBe(2);
  expect(
    fetcher.mock.calls.filter(([path]) => path.endsWith("/results")),
  ).toHaveLength(1);
});

it("refreshes after a cancellation race without retrying the write", async () => {
  let cancelled = false;
  const fetcher = vi.fn(async (path: string) => {
    if (path.endsWith("/cancel")) {
      cancelled = true;
      return json({ detail: "assessment is no longer cancellable" }, 409);
    }
    if (path.endsWith("/results")) return json({ findings: [] });
    if (path.endsWith("/evidence")) return json({ evidence: [] });
    return json(
      path.endsWith("/assessments/a")
        ? assessment(cancelled ? "completed" : "running")
        : metadata(path),
    );
  });
  show(fetcher);
  await userEvent.click(
    await screen.findByRole("button", { name: "Cancel assessment" }),
  );
  expect(
    await screen.findByText(
      "No covered violations were identified. This does not certify security.",
    ),
  ).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("no longer cancellable");
  expect(
    fetcher.mock.calls.filter(([path]) => path.endsWith("/cancel")),
  ).toHaveLength(1);
  expect(
    screen.queryByRole("button", { name: "Cancel assessment" }),
  ).toBeNull();
});

it.each(["failed", "cancelled"] as Status[])(
  "keeps %s execution and pending cleanup separate",
  async (status) => {
    const fetcher = vi.fn(async (path: string) =>
      path.endsWith("/results")
        ? json({ findings: [] })
        : json(
            path.endsWith("/assessments/a")
              ? assessment(status, true)
              : metadata(path),
          ),
    );
    show(fetcher);
    expect(await screen.findByText("Pending verification")).toBeVisible();
    expect(
      await screen.findByText(
        "This assessment produced no persisted findings.",
      ),
    ).toBeVisible();
    expect(
      fetcher.mock.calls.some(([path]) => path.endsWith("/evidence")),
    ).toBe(false);
  },
);

it("aborts an in-flight assessment read when the page is disposed", async () => {
  let signal: AbortSignal | undefined;
  const fetcher = vi.fn((_path: string, options: RequestInit) => {
    signal = options.signal as AbortSignal;
    return new Promise<Response>((_resolve, reject) =>
      signal?.addEventListener("abort", () =>
        reject(new DOMException("Aborted", "AbortError")),
      ),
    );
  });
  const { unmount } = show(fetcher);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  unmount();
  expect(signal?.aborted).toBe(true);
});

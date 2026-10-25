import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { expect, it, vi } from "vitest";
import type { Assessment, Status } from "../api/types";
import AssessmentPage from "./AssessmentPage";
import { blobText, multiFindingReport, reportFixture } from "../test/report";

const assessment = (status: Status, cleanup_pending = false): Assessment => ({
  id: "a",
  project_id: "p",
  target_id: "t",
  url: "http://demo.test/",
  created_at: new Date().toISOString(),
  plugins: ["cookie-security"],
  status,
  cleanup_pending,
  plan_snapshot: reportFixture.assessment.plan_snapshot,
  result: {
    ...reportFixture.assessment.result!,
    cleanup_verified: !cleanup_pending,
    sandbox_backend: "docker",
  },
});
const finding = {
  id: "f", route_result_id: "route-id",
  plugin: "cookie-security",
  title: "SameSite configuration",
  severity: "low",
  description: "<script>synthetic</script>",
  remediation: "Set Secure.",
};
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });

it.each(["skipped", "inconclusive"] as const)(
  "shows %s checks distinctly from passed checks with zero findings", async (outcome) => {
    const item: Assessment = {
      ...assessment("completed"), plugins: ["http-security-headers"],
      result: {
        ...reportFixture.assessment.result!,
        cleanup_verified: true, sandbox_backend: "docker", finding_count: 0,
        routes: [{ ...reportFixture.assessment.result!.routes[0], finding_count: 0,
          response: {status_code: 200, media_type: outcome === "skipped" ? "application/json" : null, url: "http://demo.test/", redirects: []},
          plugins: [{id: "http-security-headers", finding_count: 0, checks: [
            {rule_id: "x-content-type-options", status: "passed", reason: "MIME protection is enabled."},
            {rule_id: "content-security-policy", status: outcome, reason: "Document applicability explains this outcome."},
            {rule_id: "framing-protection", status: outcome, reason: "Framing applicability explains this outcome."},
          ]}],
        }],
      },
    };
    show(vi.fn(async (path: string) => json(
      path.endsWith("/results") ? {findings: []} : path.endsWith("/evidence") ? {evidence: []} : path.endsWith("/assessments/a") ? item : metadata(path),
    )));
    const context = within(await screen.findByRole("region", {name: "Response and check outcomes"}));
    expect(context.getByText("200")).toBeVisible();
    expect(context.getByText(outcome === "skipped" ? "application/json" : "Unknown")).toBeVisible();
    expect(context.getByText("passed")).toBeVisible();
    expect(context.getAllByText(outcome)).toHaveLength(2);
    expect(context.getByText("Framing applicability explains this outcome.")).toBeVisible();
    expect(await screen.findByText("No covered violations were identified. This does not certify security.")).toBeVisible();
  },
);

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
  throw new Error(`Unexpected metadata request: ${path}`);
}

it.each(["plugin_error", "timeout"] as const)(
  "shows persisted provenance and an incomplete %s result after refresh", async (kind) => {
    const item = assessment("failed");
    item.result = {
      ...reportFixture.assessment.result!, execution_outcome: "failed",
      cleanup_verified: true, sandbox_backend: "docker", error_kind: kind,
      error: kind === "timeout" ? "assessment execution timed out" : "plugin cookie-security execution failed",
      execution: {
        started_at: "2026-10-12T10:00:00+00:00", deadline_at: "2026-10-12T10:01:00+00:00",
        target: {id: "t", project_id: "p", name: "Original target", kind: "docker", image: "demo", url: "http://demo.test/"},
        plugins: [{id: "cookie-security", version: "1.0.0"}],
      },
    };
    const fetcher = vi.fn(async (path: string) => json(
      path.endsWith("/results") ? {findings: []} : path.endsWith("/assessments/a") ? item : metadata(path),
    ));
    const view = show(fetcher);
    expect(await screen.findByText(item.result!.error!)).toBeVisible();
    expect(screen.getByText("cookie-security 1.0.0")).toBeVisible();
    expect(screen.getByText("2026-10-12T10:01:00.000Z")).toBeVisible();
    expect(screen.getByText("Execution was incomplete. No clean assessment can be inferred from this result.")).toBeVisible();
    expect(screen.getByRole("button", {name: "Download JSON"})).toBeEnabled();
    view.unmount();
    show(fetcher);
    expect(await screen.findByText(item.result!.error!)).toBeVisible();
    expect(screen.queryByText("No covered violations were identified. This does not certify security.")).not.toBeInTheDocument();
  },
);

it("keeps findings when evidence fails and retries evidence independently", async () => {
  let evidenceCalls = 0;
  const fetcher = vi.fn(async (path: string) => {
    if (path.endsWith("/evidence")) {
      evidenceCalls++;
      return evidenceCalls === 1
        ? json({ detail: "stored evidence is invalid" }, 500)
        : json({ evidence: multiFindingReport.evidence });
    }
    if (path.endsWith("/results")) return json({ findings: multiFindingReport.findings });
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
  expect(screen.getAllByText(multiFindingReport.findings[0].description)[0]).toBeVisible();
  expect(document.querySelector("script")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  for (const summary of screen.getAllByText("Evidence", { selector: "summary" }))
    await userEvent.click(summary);
  expect(await screen.findByText("original")).toBeVisible();
  const articles = multiFindingReport.findings.map((item) =>
    screen.getByRole("heading", { name: item.title }).closest("article")!,
  );
  expect(within(articles[0]).getAllByRole("region", { name: "Finding evidence" }).map((region) => region.textContent))
    .toEqual([expect.stringContaining("original"), expect.stringContaining("second")]);
  expect(within(articles[1]).getAllByRole("region", { name: "Finding evidence" }))
    .toHaveLength(1);
  expect(within(articles[1]).getByText("other")).toBeVisible();
  expect(within(articles[2]).queryByRole("region", { name: "Finding evidence" })).toBeNull();
  expect(evidenceCalls).toBe(2);
  expect(
    fetcher.mock.calls.filter(([path]) => path.endsWith("/results")),
  ).toHaveLength(1);
});

it("shows frozen request metadata without refetching the registered target", async () => {
  const item = multiFindingReport.assessment;
  const fetcher = vi.fn(async (path: string) => {
    if (path.includes("/targets/")) throw new Error("target must come from the frozen plan");
    if (path.endsWith("/results")) return json({ findings: [] });
    if (path.endsWith("/evidence")) return json({ evidence: [] });
    return json(path.endsWith("/assessments/a") ? item : metadata(path));
  });
  show(fetcher);
  const request = within((await screen.findByRole("heading", { name: "Assessment request" })).closest("section")!);
  expect(request.getAllByText(item.plan_snapshot.target.url)).toHaveLength(2);
  expect(request.getByText("http-security-headers, cookie-security")).toBeVisible();
  expect(fetcher.mock.calls.some(([path]) => path.includes("/targets/"))).toBe(false);
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

function exportFetcher(reportResponse: (options: RequestInit) => Promise<Response>) {
  return vi.fn(async (path: string, options: RequestInit) => {
    if (path.endsWith("/report")) return reportResponse(options);
    if (path.endsWith("/results")) return json({ findings: [finding] });
    if (path.endsWith("/evidence")) return json({ evidence: [] });
    return json(path.endsWith("/assessments/a") ? assessment("completed") : metadata(path));
  });
}

it.each(["JSON", "HTML"])("downloads %s from a fresh report without changing page reads", async (format) => {
  const createObjectURL = vi.fn((blob: Blob) => {
    expect(blob).toBeInstanceOf(Blob);
    return "blob:report";
  });
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", class extends URL { static createObjectURL = createObjectURL; static revokeObjectURL = revokeObjectURL; });
  let filename = "";
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { filename = this.download; });
  try {
    const fetcher = exportFetcher(async () => json(reportFixture));
    show(fetcher);
    const button = await screen.findByRole("button", { name: `Download ${format}` });
    await userEvent.click(button);
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    const text = await blobText(blob);
    expect(filename).toBe(`seireth-assessment-a.${format.toLowerCase()}`);
    if (format === "JSON") expect(JSON.parse(text)).toEqual(reportFixture);
    else expect(new DOMParser().parseFromString(text, "text/html").querySelector("script, img")).toBeNull();
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:report"));
    await userEvent.click(button);
    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(2));
    expect(fetcher.mock.calls.filter(([path]) => path.endsWith("/report"))).toHaveLength(2);
    expect(fetcher.mock.calls.filter(([path]) => path.endsWith("/results"))).toHaveLength(1);
    expect(screen.getByRole("heading", { name: finding.title })).toBeVisible();
  } finally { click.mockRestore(); }
});

it("shows HTML rendering failures without downloading and allows a successful retry", async () => {
  const createObjectURL = vi.fn(() => "blob:report");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", class extends URL { static createObjectURL = createObjectURL; static revokeObjectURL = revokeObjectURL; });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  let reportCalls = 0;
  try {
    const fetcher = exportFetcher(async () => json(reportCalls++ === 0 ? {
      ...reportFixture, assessment: { ...reportFixture.assessment,
        result: { ...reportFixture.assessment.result, completed_at: "20261007T120000+0000" },
      },
    } : reportFixture));
    show(fetcher);
    const html = await screen.findByRole("button", { name: "Download HTML" });
    await userEvent.click(html);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not generate the HTML report.");
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
    expect(html).toBeEnabled();
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeEnabled();
    expect(screen.getByRole("heading", { name: finding.title })).toBeVisible();
    await userEvent.click(html);
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect(reportCalls).toBe(2);
    expect(screen.queryByRole("alert")).toBeNull();
    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:report"));
  } finally { click.mockRestore(); }
});

it("aborts a pending export and suppresses downloads after navigation", async () => {
  let signal: AbortSignal | undefined;
  const createObjectURL = vi.fn();
  vi.stubGlobal("URL", class extends URL { static createObjectURL = createObjectURL; });
  const fetcher = exportFetcher((options) => {
    signal = options.signal as AbortSignal;
    return new Promise((_resolve, reject) => signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))));
  });
  const { unmount } = show(fetcher);
  await userEvent.click(await screen.findByRole("button", { name: "Download HTML" }));
  unmount();
  expect(signal?.aborted).toBe(true);
  expect(createObjectURL).not.toHaveBeenCalled();
});

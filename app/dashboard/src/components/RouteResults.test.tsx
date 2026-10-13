import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RouteResults } from "./RouteResults";
import type { Result } from "../api/types";
import { routeReportFixture } from "../test/report";

describe("persisted route outcomes", () => {
  it("renders a single-route response once through the shared check view", () => {
    const result = routeReportFixture.assessment.result;
    render(<RouteResults result={result} />);
    expect(screen.getAllByRole("region", { name: "Response and check outcomes" })).toHaveLength(1);
    expect(screen.getAllByText("Cookie attributes evaluated.")).toHaveLength(1);
    expect(screen.getByText("failed", { selector: ".check-failed" })).toBeVisible();
  });
  it("shows partial execution, withheld evidence, and unavailable comparison", () => {
    const result: Result = {
      execution_outcome: "failed", cleanup_verified: false, partial: true, finding_count: 0,
      verdict: { policy: "strict-v1", status: "blocked", reasons: ["execution did not complete"] },
      coverage: { complete: false },
      comparison: { status: "unavailable", reason: "baseline configuration differs" },
      routes: [{ key: "private", url: "https://fixture.test/private", status: "failed", error: "route request timed out",
        finding_count: 0, plugins: [], coverage: { complete: false, expected_response: false,
          missing_checks: ["http-security-headers:x-content-type-options"], failed_checks: [] } }],
    };
    render(<RouteResults result={result} />);
    expect(screen.getByText("Release blocked")).toBeInTheDocument();
    expect(screen.getByText(/withheld until cleanup/)).toBeInTheDocument();
    expect(screen.getByText(/Partial results/)).toBeInTheDocument();
    expect(screen.getByText("route request timed out")).toBeInTheDocument();
    expect(screen.getByText(/baseline configuration differs/)).toBeInTheDocument();
  });
});

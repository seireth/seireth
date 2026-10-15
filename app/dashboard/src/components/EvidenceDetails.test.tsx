import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { EvidenceDetails } from "./EvidenceDetails";
import { cspEvidenceFixture } from "../test/report";
import type { EvidenceData } from "../api/types";

it.each([
  { url: "https://example.test/", header: "content-security-policy", rule_id: "content-security-policy", status_code: 200, media_type: "text/html", condition: "missing", expected: "nonblank enforced CSP" },
  { url: "https://example.test/", header: "x-content-type-options", rule_id: "x-content-type-options", status_code: 404, media_type: null, condition: "missing", expected: "nosniff" },
  {
    url: "https://example.test/",
    header: "set-cookie",
    cookie_name: "<script>alert(1)</script>",
    secure: false,
    rule_id: "samesite-none-without-secure",
    samesite: "none",
  },
  {
    url: "https://example.test/",
    header: "set-cookie",
    cookie_name: "__Host-demo",
    secure: true,
    https: true,
    rule_id: "host-prefix",
    domain_present: false,
    root_path: true,
  },
  {
    url: "http://example.test/",
    header: "set-cookie",
    cookie_name: "__Secure-demo",
    secure: true,
    https: false,
    rule_id: "secure-prefix",
  },
  {
    url: "http://example.test/",
    header: "set-cookie",
    cookie_name: "__Host-demo",
    secure: false,
    https: false,
    rule_id: "host-prefix",
    domain_present: true,
    root_path: false,
  },
] as EvidenceData[])("renders allowed evidence as text: $header", (data) => {
  const { container } = render(
    <EvidenceDetails
      evidence={[{ id: "e", finding_id: "f", kind: "http-response", data }]}
    />,
  );
  expect(screen.getByText(data.url)).toBeVisible();
  expect(container.querySelector("script")).toBeNull();
  if ("cookie_name" in data) {
    expect(screen.getByText(data.cookie_name)).toBeVisible();
    expect(screen.getByText("Secure present").nextElementSibling).toHaveTextContent(
      data.secure ? "Yes" : "No",
    );
  }
  expect(screen.getByText("Rule").nextElementSibling).toHaveTextContent(data.rule_id);
  if ("status_code" in data) {
    expect(screen.getByText("HTTP status").nextElementSibling).toHaveTextContent(String(data.status_code));
    expect(screen.getByText("Declared media type").nextElementSibling).toHaveTextContent(data.media_type ?? "Unknown");
  }
  if ("condition" in data) {
    expect(screen.getByText("Observed condition").nextElementSibling).toHaveTextContent(data.condition);
    expect(screen.getByText("Expected requirement").nextElementSibling).toHaveTextContent(data.expected);
  }
  if ("https" in data)
    expect(screen.getByText("HTTPS response").nextElementSibling).toHaveTextContent(
      data.https ? "Yes" : "No",
    );
  if ("domain_present" in data) {
    expect(
      screen.getByText("Nonempty Domain present").nextElementSibling,
    ).toHaveTextContent(data.domain_present ? "Yes" : "No");
    expect(screen.getByText("Explicit Path=/").nextElementSibling).toHaveTextContent(
      data.root_path ? "Yes" : "No",
    );
  }
});

it("explains CSP permissions with complete policy and execution context details", () => {
  render(<EvidenceDetails evidence={[cspEvidenceFixture]} />);
  expect(screen.getByText("Enforced policies").nextElementSibling).toHaveTextContent("2");
  const observations = screen.getAllByRole("listitem");
  expect(observations.map((item) => item.textContent)).toEqual([
    "Policy 1: Inline script elements ; script-src-elem ; Effective unsafe-inline permission",
    "Policy 2: Inline script elements ; No script directive ; No applicable script directive",
    "Policy 1: Inline event handlers ; script-src-attr ; Effective unsafe-inline permission",
    "Policy 2: Inline event handlers ; No script directive ; No applicable script directive",
  ]);
  expect(screen.getByText("csp-inline-scripts")).toBeVisible();
  expect(screen.queryByText("Expected requirement")).toBeNull();
});

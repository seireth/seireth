import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import ScopeForm, { defaultExpiry, expiryTimestamp } from "./ScopeForm";

it("defaults to fifteen local minutes and sends an explicit timezone", () => {
  const now = Date.now();
  expect(
    Math.abs(new Date(defaultExpiry(now)).getTime() - now - 15 * 60_000),
  ).toBeLessThan(60_000);
  const local = "2026-10-02T12:30";
  expect(expiryTimestamp(local)).toBe(new Date(local).toISOString());
  expect(expiryTimestamp(local)).toMatch(/Z$/);
});
it("retains inputs on API failure and sends a single authorization request", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "scope must be bounded to the registered target",
        }),
        { status: 400 },
      ),
    );
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ScopeForm
        target={{
          id: "t",
          project_id: "p",
          name: "Demo",
          image: "demo",
          url: "https://demo.test/",
        }}
      />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  const url = screen.getByLabelText("Authorized URL");
  await user.clear(url);
  await user.type(url, "https://other.test/");
  await user.click(
    screen.getByRole("button", { name: "Create authorization scope" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("bounded");
  expect(url).toHaveValue("https://other.test/");
  expect(fetch).toHaveBeenCalledTimes(1);
});

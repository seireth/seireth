import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { newRoute, RoutePlanEditor, selectRoutePlugins } from "./RoutePlanEditor";

it("keeps generated route keys unique after removing and adding a route", async () => {
  function Editor() {
    const [routes, setRoutes] = useState([newRoute("", "route-1"), newRoute("", "route-2"), newRoute("", "route-3")]);
    return <RoutePlanEditor routes={routes} onChange={setRoutes} selectedPlugins={[]} />;
  }
  render(<Editor />);
  const user = userEvent.setup();
  await user.click(screen.getAllByRole("button", { name: "Remove route" })[1]);
  await user.click(screen.getByRole("button", { name: "Add route" }));
  expect(screen.getAllByLabelText("Route key").map(input => (input as HTMLInputElement).value))
    .toEqual(["route-1", "route-3", "route-4"]);
});


it("preserves inferred checks and explicit expectation-only selection", () => {
  expect(selectRoutePlugins(newRoute(), ["csp-policy"], true).requiredChecks).toBeUndefined();
  expect(selectRoutePlugins({ ...newRoute(), requiredChecks: [] }, ["csp-policy"], true)).toMatchObject({ requiredChecks: [], plugins: undefined });
});

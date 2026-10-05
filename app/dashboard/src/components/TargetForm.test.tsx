import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import TargetForm from "./TargetForm";

it("requires an explicit target URL and registers only the operator's input", async () => {
  const fetcher = vi.fn((_path: string, options?: RequestInit) =>
    Promise.resolve(
      new Response(
        JSON.stringify(
          options?.method === "POST"
            ? { id: "target" }
            : {
                sandbox_backend: "docker",
                default_target_image: "allowed",
                allowed_target_images: ["allowed"],
              },
        ),
      ),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  const onCreated = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TargetForm projectId="project" onCreated={onCreated} />
    </QueryClientProvider>,
  );
  await screen.findByRole("option", { name: "allowed" });
  const user = userEvent.setup();
  const url = screen.getByLabelText("Registered URL");
  const submit = screen.getByRole("button", { name: "Register target" });
  expect(url).toHaveValue("");
  await user.type(screen.getByLabelText("Target name"), "Owned target");
  expect(submit).toBeDisabled();
  await user.click(submit);
  expect(fetcher.mock.calls.filter(([, options]) => options?.method === "POST"))
    .toHaveLength(0);
  await user.type(url, "https://owned.test/");
  await user.click(submit);
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith("target"));
  const writes = fetcher.mock.calls.filter(([, options]) => options?.method === "POST");
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0][1]?.body))).toEqual({
    project_id: "project",
    name: "Owned target",
    url: "https://owned.test/",
    image: "allowed",
  });
});

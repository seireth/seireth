import { expect, it, vi } from "vitest";
import { ApiError, post, request } from "./client";

it("makes one relative JSON write and extracts field errors without input values", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: [
            {
              loc: ["body", "url"],
              msg: "Invalid URL",
              input: "synthetic-secret",
            },
          ],
        }),
        { status: 422 },
      ),
    );
  vi.stubGlobal("fetch", fetch);
  const error = await post("/targets", { url: "invalid" }).catch(
    (error) => error,
  );
  if (!(error instanceof ApiError)) throw error;
  expect(error).toBeInstanceOf(ApiError);
  expect(error.fields).toEqual({ url: "Invalid URL" });
  expect(error.message).not.toContain("synthetic-secret");
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/api/v1/targets");
});
it("passes an abort signal to reads", async () => {
  const controller = new AbortController();
  const fetch = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", fetch);
  await request("/projects", { signal: controller.signal });
  expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
});

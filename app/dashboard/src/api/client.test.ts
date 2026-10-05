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

it.each(["<html>wrong upstream</html>", ""])(
  "rejects a successful response without valid JSON: %j",
  async (body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
    await expect(request("/projects")).rejects.toBeInstanceOf(SyntaxError);
  },
);

it("preserves the HTTP error when its response is not JSON", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("Bad gateway", { status: 502 })),
  );
  await expect(request("/projects")).rejects.toMatchObject({
    status: 502,
    message: "Request failed (502)",
    fields: {},
  });
});

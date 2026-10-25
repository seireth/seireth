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

it.each(["<html>wrong upstream</html>", ""])(
  "rejects a successful response without valid JSON: %j",
  async (body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
    await expect(request("/projects")).rejects.toBeInstanceOf(SyntaxError);
  },
);

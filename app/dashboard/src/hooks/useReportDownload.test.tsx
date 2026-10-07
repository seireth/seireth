import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { reportFixture } from "../test/report";
import { useReportDownload } from "./useReportDownload";

function setup() {
  const client = new QueryClient();
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return renderHook(({ id }) => useReportDownload(id), {
    wrapper,
    initialProps: { id: "a" },
  });
}

it("guards simultaneous clicks before the pending state renders", async () => {
  let resolve!: (response: Response) => void;
  const fetcher = vi.fn(() => new Promise<Response>((done) => { resolve = done; }));
  vi.stubGlobal("fetch", fetcher);
  const { result } = setup();
  act(() => {
    result.current.download("json");
    result.current.download("html");
  });
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  act(() => resolve(new Response(JSON.stringify({ detail: "invalid report" }), { status: 500 })));
  await waitFor(() => expect(result.current.error?.message).toBe("invalid report"));
});

it("resets export state on assessment navigation and rejects a late response even if fetch ignores abort", async () => {
  let resolve!: (response: Response) => void;
  let signal: AbortSignal | undefined;
  const fetcher = vi.fn((_path: string, options: RequestInit) => {
    signal = options.signal as AbortSignal;
    return new Promise<Response>((done) => { resolve = done; });
  });
  const createObjectURL = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("URL", class extends URL { static createObjectURL = createObjectURL; });
  const { result, rerender } = setup();
  act(() => result.current.download("json"));
  await waitFor(() => expect(result.current.isPending).toBe(true));
  rerender({ id: "b" });
  expect(signal?.aborted).toBe(true);
  await act(async () => { resolve(new Response(JSON.stringify(reportFixture))); });
  expect(result.current.error).toBeNull();
  expect(result.current.isPending).toBe(false);
  expect(createObjectURL).not.toHaveBeenCalled();
});

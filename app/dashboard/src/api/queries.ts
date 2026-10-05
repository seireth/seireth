import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { request } from "./client";
import type { Page } from "./types";

export function useResource<T>(path: string, enabled = true) {
  return useQuery({
    queryKey: [path],
    queryFn: ({ signal }) => request<T>(path, { signal }),
    enabled,
  });
}
export function useList<T>(path: string, enabled = true) {
  return useInfiniteQuery({
    queryKey: [path],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      request<Page<T>>(
        `${path}${path.includes("?") ? "&" : "?"}limit=50&offset=${pageParam}`,
        { signal },
      ),
    getNextPageParam: (last, pages) =>
      last.has_more ? pages.length * 50 : undefined,
    enabled,
  });
}

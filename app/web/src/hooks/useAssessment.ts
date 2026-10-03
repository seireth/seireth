import { useQuery } from "@tanstack/react-query";
import { request } from "../api/client";
import type { Assessment } from "../api/types";

export const terminal = (status: Assessment["status"]) =>
  ["completed", "failed", "cancelled"].includes(status);
export function pollingInterval(assessment?: Assessment) {
  if (!assessment) return 1000;
  return !terminal(assessment.status)
    ? 1000
    : assessment.cleanup_pending
      ? 5000
      : false;
}
export function useAssessment(id: string) {
  return useQuery({
    queryKey: [`/assessments/${id}`],
    queryFn: ({ signal }) =>
      request<Assessment>(`/assessments/${id}`, { signal }),
    refetchInterval: (query) => pollingInterval(query.state.data),
  });
}

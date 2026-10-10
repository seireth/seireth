import { useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { request } from "../api/client";
import type { AssessmentReport } from "../api/types";
import { downloadBlob, htmlReport } from "../reports";

export function useReportDownload(id: string) {
  const active = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      active.current?.abort();
      active.current = null;
    },
    [id],
  );
  const mutation = useMutation({
    mutationKey: ["assessment-report", id],
    mutationFn: async ({ format, controller }: {
        format: "json" | "html";
        controller: AbortController;
      }) => {
      try {
        const report = await request<AssessmentReport>(`/assessments/${id}/report`, {
          signal: controller.signal,
          cache: "no-store",
        });
        controller.signal.throwIfAborted();
        const content = format === "json"
          ? JSON.stringify(report, null, 2)
          : htmlReport(report);
        const type = format === "json" ? "application/json" : "text/html";
        downloadBlob(
          new Blob([content], { type: `${type};charset=utf-8` }),
          `seireth-assessment-${report.assessment.id}.${format}`,
        );
      } finally {
        if (active.current === controller) active.current = null;
      }
    },
    retry: false,
  });
  return {
    isPending: mutation.isPending,
    error: mutation.error,
    download(format: "json" | "html") {
      if (active.current) return;
      const controller = new AbortController();
      active.current = controller;
      mutation.mutate({ format, controller });
    },
  };
}

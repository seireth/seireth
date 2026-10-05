import { describe, expect, it } from "vitest";
import { pollingInterval } from "./useAssessment";
import type { Assessment, Status } from "../api/types";

describe("assessment polling", () => {
  it.each(["queued", "running", "cancelling", "recovering"] as Status[])(
    "polls %s execution each second",
    (status) => {
      expect(
        pollingInterval({ status, cleanup_pending: false } as Assessment),
      ).toBe(1000);
    },
  );
  it.each(["completed", "failed", "cancelled"] as Status[])(
    "stops for %s only after cleanup resolves",
    (status) => {
      expect(
        pollingInterval({ status, cleanup_pending: false } as Assessment),
      ).toBe(false);
      expect(
        pollingInterval({ status, cleanup_pending: true } as Assessment),
      ).toBe(5000);
    },
  );
});

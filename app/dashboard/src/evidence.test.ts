import { expect, it } from "vitest";
import { groupEvidenceByFinding } from "./evidence";
import { multiFindingReport } from "./test/report";

it("groups interleaved evidence without sorting or changing its records", () => {
  const evidence = Object.freeze(multiFindingReport.evidence.map((entry) =>
    Object.freeze({ ...entry, data: Object.freeze({ ...entry.data }) }),
  ));
  const before = JSON.stringify(evidence);
  const grouped = groupEvidenceByFinding(evidence);

  expect(grouped.get("f")).toEqual([evidence[0], evidence[2]]);
  expect(grouped.get("other")).toEqual([evidence[1]]);
  expect(grouped.get("empty")).toBeUndefined();
  expect(grouped.get("f")?.[0]).toBe(evidence[0]);
  expect(grouped.get("f")?.[1]).toBe(evidence[2]);
  expect(JSON.stringify(evidence)).toBe(before);
});

it("returns no groups when evidence is absent", () => {
  expect(groupEvidenceByFinding([]).size).toBe(0);
});

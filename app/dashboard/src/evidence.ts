import type { Evidence } from "./api/types";

export function groupEvidenceByFinding(evidence: readonly Evidence[]): Map<string, Evidence[]> {
  const grouped = new Map<string, Evidence[]>();
  for (const entry of evidence) {
    const entries = grouped.get(entry.finding_id);
    if (entries) entries.push(entry);
    else grouped.set(entry.finding_id, [entry]);
  }
  return grouped;
}

import type { DagsterSnapshot, DagsterRun } from "@kor-travel/ui/dagster-model";
export type ConciergeDagsterRun = DagsterRun & { domainRunId: number | null };
export type ConciergeSnapshot = Omit<DagsterSnapshot, "runs"> & { runs: ConciergeDagsterRun[] };
export type DagsterSummary = {
  status: "ok" | "degraded";
  snapshot: ConciergeSnapshot | null;
  error: string | null;
  publicUrl: string;
};

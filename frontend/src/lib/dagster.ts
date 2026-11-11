import { z } from "zod";
import type { DagsterSnapshot, DagsterRun } from "@kor-travel/ui/dagster-model";
export type ConciergeDagsterRun = DagsterRun & { domainRunId: number | null };
export type ConciergeSnapshot = Omit<DagsterSnapshot, "runs"> & { runs: ConciergeDagsterRun[] };
export type DagsterSummary = {
  status: "ok" | "degraded";
  snapshot: ConciergeSnapshot | null;
  error: string | null;
  publicUrl: string;
};

// 타입 단언만으로 HTTP payload를 신뢰하지 않는다. 화면에서 순회·문자열 처리하는
// 계약 전체를 확인한 뒤 last-good 상태를 한 번에 교체한다.
const tickSchema = z.looseObject({
  status: z.string(), timestamp: z.number().finite().nullable(),
  errorMessage: z.string().nullable().optional(),
});
const scheduleSchema = z.looseObject({
  name: z.string(), status: z.string().nullable(), cron: z.string().nullable(),
  jobName: z.string().nullable(), lastTick: tickSchema.nullable().optional(),
  timezone: z.string().nullable().optional(), overdue: z.boolean().optional(),
});
const snapshotSchema = z.looseObject({
  checkedAt: z.string(),
  runs: z.array(z.looseObject({
    runId: z.string(), status: z.string(), jobName: z.string(),
    startTime: z.number().finite().nullable(), endTime: z.number().finite().nullable(),
    errorMessage: z.string().nullable(), domainRunId: z.number().int().positive().nullable(),
    maxRuntimeSeconds: z.number().finite().positive().nullable().optional(),
  })),
  repositories: z.array(z.looseObject({
    name: z.string(), locationName: z.string(), jobs: z.array(z.string()),
    assets: z.array(z.string()), assetCount: z.number().int().nonnegative().optional(),
    schedules: z.array(scheduleSchema),
    sensors: z.array(z.looseObject({ name: z.string(), status: z.string().nullable(),
      lastTick: tickSchema.nullable().optional() })).optional(),
  })),
});
const healthySummarySchema = z.looseObject({
  status: z.literal("ok"), snapshot: snapshotSchema,
  error: z.string().nullable().optional(),
  publicUrl: z.url().refine(value => ["http:", "https:"].includes(new URL(value).protocol)),
});

export function parseHealthyDagsterSummary(payload: unknown): DagsterSummary & { snapshot: ConciergeSnapshot } {
  const parsed = healthySummarySchema.parse(payload);
  return { ...parsed, error: parsed.error ?? null };
}

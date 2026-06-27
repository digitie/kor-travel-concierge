"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  DatabaseIcon,
  HardDriveIcon,
  ListChecksIcon,
  RefreshCwIcon,
} from "lucide-react";

import {
  getMetrics,
  getRustfsStatus,
  listAuditLogs,
  listRuns,
  listRunQueue,
  USER_JOB_TYPES,
  type CrawlRunSummary,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

function asNum(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function asRecord(value: unknown): Record<string, number> {
  return value && typeof value === "object"
    ? (value as Record<string, number>)
    : {};
}

function formatBytes(bytes: number | undefined): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function targetLabel(run: CrawlRunSummary): string {
  return run.target_label ?? run.target_id ?? run.source ?? "-";
}

function progressPercent(run: CrawlRunSummary): string {
  return `${Math.round(run.progress * 100)}%`;
}

export function StatusDashboard() {
  const queueQuery = useQuery({
    queryKey: ["run-queue", "status"],
    queryFn: () => listRunQueue(USER_JOB_TYPES),
    refetchInterval: 3_000,
  });
  const runsQuery = useQuery({
    queryKey: ["runs", "status"],
    queryFn: () => listRuns({ limit: 30, jobTypes: USER_JOB_TYPES }),
    refetchInterval: 5_000,
  });
  const metricsQuery = useQuery({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    refetchInterval: 10_000,
  });
  const rustfsQuery = useQuery({
    queryKey: ["rustfs-status"],
    queryFn: getRustfsStatus,
    refetchInterval: 15_000,
  });
  const auditQuery = useQuery({
    queryKey: ["audit-logs"],
    queryFn: listAuditLogs,
    refetchInterval: 15_000,
  });

  const queueRuns = queueQuery.data ?? [];
  const running = queueRuns.filter((run) => run.state === "running");
  const pending = queueRuns.filter((run) => run.state === "pending");
  const metrics = metricsQuery.data;
  const db = metrics?.database ?? {};
  const runsByState = asRecord(db.runs_by_state);
  const candidatesByStatus = asRecord(db.candidates_by_status);
  const storage = metrics?.storage;
  const rustfs = rustfsQuery.data;

  function refresh() {
    void queueQuery.refetch();
    void runsQuery.refetch();
    void metricsQuery.refetch();
    void rustfsQuery.refetch();
    void auditQuery.refetch();
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <Button type="button" variant="outline" size="sm" onClick={refresh}>
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      </div>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={<ListChecksIcon className="size-4" />}
          label="실행 큐"
          value={`실행 ${running.length} · 대기 ${pending.length}`}
          tone={running.length > 0 ? "active" : "neutral"}
        />
        <MetricCard
          icon={<DatabaseIcon className="size-4" />}
          label="DB 장소/영상"
          value={`${asNum(db.travel_places).toLocaleString()} 장소 · ${asNum(
            db.youtube_videos,
          ).toLocaleString()} 영상`}
        />
        <MetricCard
          icon={<HardDriveIcon className="size-4" />}
          label="RustFS"
          value={`${storage?.health?.ok || rustfs?.health?.ok ? "정상" : "확인 필요"} · ${formatBytes(
            storage?.total_size_bytes,
          )}`}
          tone={storage?.health?.ok || rustfs?.health?.ok ? "neutral" : "warn"}
        />
        <MetricCard
          icon={<AlertTriangleIcon className="size-4" />}
          label="검수 후보"
          value={Object.entries(candidatesByStatus)
            .map(([key, value]) => `${key} ${value}`)
            .join(" · ") || "후보 없음"}
          tone={asNum(candidatesByStatus.needs_review) > 0 ? "warn" : "neutral"}
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <Panel title="실행 큐 상세">
          {queueQuery.isError ? (
            <p className="text-sm text-destructive">{queueQuery.error.message}</p>
          ) : queueRuns.length > 0 ? (
            <div className="overflow-x-auto rounded-lg border border-surface-muted">
              <table className="w-full text-[13px]">
                <thead className="bg-surface-subtle text-left text-[12px] font-bold uppercase text-text-secondary">
                  <tr>
                    <th className="px-3 py-2">상태</th>
                    <th className="px-3 py-2">대상</th>
                    <th className="px-3 py-2">진행</th>
                    <th className="px-3 py-2">메시지</th>
                    <th className="px-3 py-2">상세</th>
                  </tr>
                </thead>
                <tbody>
                  {queueRuns.map((run) => (
                    <tr key={run.job_id} className="border-t border-surface-muted">
                      <td className="px-3 py-2">
                        <Badge variant={run.state === "running" ? "secondary" : "outline"}>
                          {run.state}
                        </Badge>
                      </td>
                      <td className="px-3 py-2">
                        <div className="max-w-[18rem] whitespace-normal">
                          <div className="font-medium">{targetLabel(run)}</div>
                          <div className="text-[12px] text-text-secondary">
                            {run.job_type_label ?? run.job_type}
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2">{progressPercent(run)}</td>
                      <td className="px-3 py-2">
                        <span className="line-clamp-2 text-text-secondary">
                          {run.current_message ?? run.status_logs.at(-1)?.message ?? "-"}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <Link
                          href={`/jobs/${run.job_id}`}
                          className="font-medium text-brand hover:underline"
                        >
                          열기
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState>실행 중이거나 대기 중인 작업이 없습니다.</EmptyState>
          )}
        </Panel>

        <Panel title="작업 상태 집계">
          <CountList counts={runsByState} empty="작업 기록이 없습니다." />
        </Panel>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Panel title="최근 작업">
          {(runsQuery.data ?? []).length > 0 ? (
            <div className="flex flex-col divide-y divide-surface-muted rounded-lg border border-surface-muted">
              {(runsQuery.data ?? []).map((run) => (
                <Link
                  key={run.job_id}
                  href={`/jobs/${run.job_id}`}
                  className="flex items-start justify-between gap-3 px-3 py-2.5 text-[13px] transition-colors hover:bg-surface-subtle"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">
                      {targetLabel(run)}
                    </span>
                    <span className="line-clamp-1 text-text-secondary">
                      {run.current_message ?? run.status_logs.at(-1)?.message ?? "-"}
                    </span>
                  </span>
                  <span className="flex shrink-0 flex-col items-end gap-1">
                    <Badge variant={run.state === "failed" ? "destructive" : "outline"}>
                      {run.state}
                    </Badge>
                    <span className="text-[12px] text-text-secondary">
                      {formatDateTime(run.finished_at ?? run.started_at ?? run.created_at)}
                    </span>
                  </span>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState>최근 작업이 없습니다.</EmptyState>
          )}
        </Panel>

        <Panel title="저장소 상세">
          <div className="grid grid-cols-2 gap-2">
            <Metric label="상태" value={rustfs?.health?.ok ? "정상" : "확인 필요"} />
            <Metric
              label="객체 수"
              value={asNum(storage?.total_objects).toLocaleString()}
            />
            <Metric label="총 용량" value={formatBytes(storage?.total_size_bytes)} />
            <Metric label="보존 정책" value={rustfs?.retention_policy ?? "-"} />
          </div>
          {(storage?.assets ?? rustfs?.assets ?? []).length > 0 ? (
            <div className="mt-3 flex flex-col divide-y divide-surface-muted rounded-lg border border-surface-muted text-[13px]">
              {(storage?.assets ?? rustfs?.assets ?? []).map((asset) => (
                <div
                  key={asset.asset_type}
                  className="flex items-center justify-between gap-3 px-3 py-2"
                >
                  <span className="text-text-secondary">{asset.asset_type}</span>
                  <span>
                    {asset.count.toLocaleString()}개 · {formatBytes(asset.size_bytes)}
                  </span>
                </div>
              ))}
            </div>
          ) : null}
        </Panel>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Panel title="검수 후보 상태">
          <CountList counts={candidatesByStatus} empty="검수 후보가 없습니다." />
        </Panel>
        <Panel title="최근 감사 로그">
          {(auditQuery.data ?? []).length > 0 ? (
            <div className="flex flex-col divide-y divide-surface-muted rounded-lg border border-surface-muted text-[13px]">
              {(auditQuery.data ?? []).map((log) => (
                <div key={log.id} className="px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{log.action}</span>
                    <span className="text-[12px] text-text-secondary">
                      {formatDateTime(log.created_at)}
                    </span>
                  </div>
                  <p className="truncate text-text-secondary">
                    {log.actor_type} · {log.target_type}
                    {log.target_id ? ` #${log.target_id}` : ""}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState>감사 로그가 없습니다.</EmptyState>
          )}
        </Panel>
      </section>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  tone = "neutral",
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone?: "neutral" | "active" | "warn";
}) {
  return (
    <div className="flex min-w-0 items-start gap-3 rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]">
      <span
        className={
          tone === "active"
            ? "mt-0.5 text-brand"
            : tone === "warn"
              ? "mt-0.5 text-warning"
              : "mt-0.5 text-text-secondary"
        }
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block text-[12px] font-bold uppercase tracking-[0.05em] text-text-secondary">
          {label}
        </span>
        <span className="mt-1 block text-[16px] font-bold leading-snug text-text-primary">
          {value}
        </span>
      </span>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]">
      <h2 className="mb-3 flex items-center gap-1.5 text-[14px] font-bold">
        <CheckCircle2Icon className="size-4 text-brand" />
        {title}
      </h2>
      {children}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-surface-muted bg-surface-subtle p-2.5">
      <span className="text-[12px] text-text-secondary">{label}</span>
      <span className="font-bold">{value}</span>
    </div>
  );
}

function CountList({
  counts,
  empty,
}: {
  counts: Record<string, number>;
  empty: string;
}) {
  const entries = Object.entries(counts);
  if (entries.length === 0) {
    return <EmptyState>{empty}</EmptyState>;
  }
  return (
    <div className="flex flex-col divide-y divide-surface-muted rounded-lg border border-surface-muted text-[13px]">
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-center justify-between gap-3 px-3 py-2">
          <span className="text-text-secondary">{key}</span>
          <span className="font-medium">{value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-surface-muted bg-surface-subtle p-3 text-[13px] text-text-secondary">
      {children}
    </p>
  );
}

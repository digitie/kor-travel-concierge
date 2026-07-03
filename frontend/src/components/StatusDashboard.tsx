"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangleIcon,
  DatabaseIcon,
  HardDriveIcon,
  ListChecksIcon,
  RefreshCwIcon,
} from "lucide-react";

import {
  getMetrics,
  getRustfsStatus,
  listAuditLogs,
  listLoginEvents,
  listRuns,
  listRunQueue,
  USER_JOB_TYPES,
  type CrawlRunSummary,
} from "@/lib/api";
import {
  assetTypeLabel,
  candidateStatusLabel,
  categoryDisplayLabel,
  jobTypeDisplayLabel,
  loginEventLabel,
  loginOutcomeLabel,
  runProgressBarClass,
  runStateBadgeVariant,
  runStateLabel,
  targetTypeDisplayLabel,
} from "@/lib/display-labels";
import { asNum, asRecord, formatBytes, formatDateTimeShort } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  CountList,
  EmptyState,
  Metric,
  MetricCard,
  Panel,
  Section,
} from "@/components/panels";

function targetLabel(run: CrawlRunSummary): string {
  return run.target_label ?? run.target_id ?? run.source ?? "-";
}

function progressPercent(run: CrawlRunSummary): string {
  return `${Math.round(run.progress * 100)}%`;
}

function auditActionLabel(value: string): string {
  if (value.includes("settings")) return "설정";
  if (value.includes("api_key")) return "API 키";
  if (value.includes("login")) return "로그인";
  return value.replaceAll("_", " ").replaceAll(".", " ");
}

function auditTargetLabel(value: string): string {
  if (value === "admin") return "관리자";
  if (value === "api_key") return "API 키";
  if (value === "setting") return "설정";
  return value.replaceAll("_", " ");
}

export function StatusDashboard() {
  const queueQuery = useQuery({
    queryKey: ["run-queue", "status"],
    queryFn: () => listRunQueue(USER_JOB_TYPES),
    refetchInterval: 3_000,
  });
  const runsQuery = useQuery({
    queryKey: ["runs", "status"],
    queryFn: () => listRuns({ limit: 80, jobTypes: USER_JOB_TYPES }),
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
  const loginEventsQuery = useQuery({
    queryKey: ["login-events", "status"],
    queryFn: listLoginEvents,
    refetchInterval: 15_000,
  });

  const queueRuns = queueQuery.data ?? [];
  const historyRuns = (runsQuery.data ?? []).filter(
    (run) =>
      run.state.toLowerCase() !== "running" &&
      run.state.toLowerCase() !== "pending",
  );
  const running = queueRuns.filter(
    (run) => run.state.toLowerCase() === "running",
  );
  const pending = queueRuns.filter(
    (run) => run.state.toLowerCase() === "pending",
  );
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
    void loginEventsQuery.refetch();
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[16px] font-bold">운영 요약</h2>
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
            .map(([key, value]) => `${candidateStatusLabel(key)} ${value}`)
            .join(" · ") || "후보 없음"}
          tone={asNum(candidatesByStatus.needs_review) > 0 ? "warn" : "neutral"}
        />
      </section>

      <Section title="작업">
        <section className="grid gap-4 xl:grid-cols-[1fr_18rem]">
          <Panel title="작업 테이블">
            {queueQuery.isError ? (
              <p className="mb-2 text-sm text-destructive">
                {queueQuery.error.message}
              </p>
            ) : null}
            {runsQuery.isError ? (
              <p className="mb-2 text-sm text-destructive">
                {runsQuery.error.message}
              </p>
            ) : null}
            <Tabs defaultValue="active">
              <TabsList>
                <TabsTrigger value="active">진행 중 {queueRuns.length}</TabsTrigger>
                <TabsTrigger value="history">완료 이력 {historyRuns.length}</TabsTrigger>
              </TabsList>
              <TabsContent value="active" className="mt-3">
                <RunStatusTable
                  runs={queueRuns}
                  empty="실행 중이거나 대기 중인 작업이 없습니다."
                />
              </TabsContent>
              <TabsContent value="history" className="mt-3">
                <RunStatusTable
                  runs={historyRuns}
                  empty="완료된 작업 이력이 없습니다."
                />
              </TabsContent>
            </Tabs>
          </Panel>

          <Panel title="작업 상태 집계">
            <CountList
              counts={runsByState}
              empty="작업 기록이 없습니다."
              labeler={runStateLabel}
            />
          </Panel>
        </section>
      </Section>

      <Section title="데이터">
        <section className="grid gap-4 xl:grid-cols-2">
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
                    <span className="text-text-secondary">
                      {assetTypeLabel(asset.asset_type)}
                    </span>
                    <span>
                      {asset.count.toLocaleString()}개 · {formatBytes(asset.size_bytes)}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </Panel>

          <Panel title="검수 후보 상태">
            <CountList
              counts={candidatesByStatus}
              empty="검수 후보가 없습니다."
              labeler={candidateStatusLabel}
            />
          </Panel>
        </section>
      </Section>

      <Section title="보안">
        <section className="grid gap-4 xl:grid-cols-2">
          <Panel title="로그인 기록">
            {(loginEventsQuery.data ?? []).length > 0 ? (
              <div className="max-h-80 overflow-y-auto rounded-lg border border-surface-muted text-[13px]">
                {(loginEventsQuery.data ?? []).map((event) => (
                  <div
                    key={event.id}
                    className="border-b border-surface-muted px-3 py-2 last:border-b-0"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">
                        {loginEventLabel(event.event_type)}
                      </span>
                      <Badge
                        variant={
                          event.outcome === "succeeded" ? "secondary" : "outline"
                        }
                      >
                        {loginOutcomeLabel(event.outcome)}
                      </Badge>
                    </div>
                    <p className="mt-1 text-[12px] text-text-secondary">
                      {formatDateTimeShort(event.created_at)} ·{" "}
                      {event.attempted_username || "-"} · {event.reason || "-"}
                    </p>
                    <p className="truncate text-[12px] text-text-secondary">
                      {event.client_ip || "unknown ip"}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState>저장된 로그인 기록이 없습니다.</EmptyState>
            )}
          </Panel>

          <Panel title="최근 감사 로그">
            {(auditQuery.data ?? []).length > 0 ? (
              <div className="flex max-h-80 flex-col divide-y divide-surface-muted overflow-y-auto rounded-lg border border-surface-muted text-[13px]">
                {(auditQuery.data ?? []).map((log) => (
                  <div key={log.id} className="px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{auditActionLabel(log.action)}</span>
                      <span className="text-[12px] text-text-secondary">
                        {formatDateTimeShort(log.created_at)}
                      </span>
                    </div>
                    <p className="truncate text-text-secondary">
                      {auditTargetLabel(log.actor_type)} ·{" "}
                      {auditTargetLabel(log.target_type)}
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
      </Section>
    </div>
  );
}

function RunStatusTable({
  runs,
  empty,
}: {
  runs: CrawlRunSummary[];
  empty: string;
}) {
  if (runs.length === 0) {
    return (
      <div className="flex h-[28rem] items-start">
        <EmptyState>{empty}</EmptyState>
      </div>
    );
  }

  return (
    <div className="max-h-[28rem] overflow-auto rounded-lg border border-surface-muted">
      <table className="w-full min-w-[64rem] text-[13px]">
        <thead className="sticky top-0 z-10 bg-surface-subtle text-left text-[12px] font-bold text-text-secondary">
          <tr>
            <th className="px-3 py-2">상태</th>
            <th className="px-3 py-2">작업/대상</th>
            <th className="px-3 py-2">기본</th>
            <th className="px-3 py-2">진행</th>
            <th className="px-3 py-2">메시지</th>
            <th className="px-3 py-2">시간</th>
            <th className="px-3 py-2 text-right">상세</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.job_id} className="border-t border-surface-muted">
              <td className="px-3 py-2 align-top">
                <Badge variant={runStateBadgeVariant(run.state)}>
                  {runStateLabel(run.state)}
                </Badge>
              </td>
              <td className="px-3 py-2 align-top">
                <div className="flex max-w-[20rem] flex-col gap-1 whitespace-normal">
                  <span className="text-[11px] font-bold text-text-secondary">
                    {run.target_type_label ?? targetTypeDisplayLabel(run.target_type)}
                    {" · "}
                    {run.job_type_label ?? jobTypeDisplayLabel(run.job_type)}
                  </span>
                  <span className="font-bold leading-snug">{targetLabel(run)}</span>
                  <span className="font-mono text-[11px] text-text-secondary">
                    {run.job_id}
                  </span>
                </div>
              </td>
              <td className="px-3 py-2 align-top">
                <Badge variant="outline">
                  {categoryDisplayLabel(
                    run.default_category_label ?? run.default_category_code,
                  )}
                </Badge>
              </td>
              <td className="px-3 py-2 align-top">
                <div className="flex w-28 flex-col gap-1">
                  <div className="h-1.5 overflow-hidden rounded-full bg-surface-muted">
                    <div
                      className={runProgressBarClass(run.state)}
                      style={{ width: progressPercent(run) }}
                    />
                  </div>
                  <span className="text-[12px] text-text-secondary">
                    {progressPercent(run)}
                  </span>
                </div>
              </td>
              <td className="px-3 py-2 align-top">
                <div className="max-w-[22rem] text-text-secondary">
                  <p className="line-clamp-2 whitespace-normal">
                    {run.current_message ?? run.status_logs.at(-1)?.message ?? "-"}
                  </p>
                  {run.last_error ? (
                    <p className="line-clamp-1 text-destructive">
                      {run.last_error}
                    </p>
                  ) : null}
                </div>
              </td>
              <td className="px-3 py-2 align-top">
                <div className="flex flex-col text-[12px] text-text-secondary">
                  <span>등록 {formatDateTimeShort(run.created_at)}</span>
                  <span>시작 {formatDateTimeShort(run.started_at)}</span>
                  <span>종료 {formatDateTimeShort(run.finished_at)}</span>
                </div>
              </td>
              <td className="px-3 py-2 align-top">
                <div className="flex justify-end">
                  <Link
                    href={`/jobs/${run.job_id}`}
                    className={buttonVariants({ variant: "outline", size: "xs" })}
                  >
                    상세
                  </Link>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

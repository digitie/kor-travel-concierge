"use client";

import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
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
  listRunsPage,
  listRunQueue,
  RUN_HISTORY_REFETCH_INTERVAL_MS,
  RUN_QUEUE_OBSERVER_OPTIONS,
  RUN_QUEUE_QUERY_KEY,
  type CrawlRunSummary,
} from "@/lib/api";
import {
  assetTypeLabel,
  candidateStatusLabel,
  categoryDisplayLabel,
  jobTypeDisplayLabel,
  loginEventLabel,
  loginOutcomeLabel,
  runAttentionBadgeVariant,
  runAttentionLabel,
  runOutcomeBadgeVariant,
  runOutcomeLabel,
  runOutcomeProgressBarClass,
  runStateLabel,
  targetTypeDisplayLabel,
} from "@/lib/display-labels";
import { asNum, asRecord, formatBytes, formatDateTimeShort } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  RunActionButtons,
  type RunActionFeedback,
} from "@/components/RunActionButtons";
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

function subscribeClientState() {
  return () => undefined;
}

function getClientSnapshot() {
  return true;
}

function getServerSnapshot() {
  return false;
}

export function StatusDashboard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const mounted = useSyncExternalStore(
    subscribeClientState,
    getClientSnapshot,
    getServerSnapshot,
  );
  const [runActionFeedback, setRunActionFeedback] =
    useState<RunActionFeedback | null>(null);
  const queueQuery = useQuery({
    queryKey: RUN_QUEUE_QUERY_KEY,
    queryFn: listRunQueue,
    ...RUN_QUEUE_OBSERVER_OPTIONS,
  });
  const attentionOnly = searchParams.get("attention") === "open";
  const runsQuery = useInfiniteQuery({
    queryKey: ["runs", "status", attentionOnly],
    queryFn: ({ pageParam }) =>
      listRunsPage({
        terminal: true,
        attention: attentionOnly ? "open" : undefined,
        userJobsOnly: true,
        limit: 80,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor : undefined,
    staleTime: 60_000,
    refetchInterval: RUN_HISTORY_REFETCH_INTERVAL_MS,
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

  const queueRuns = queueQuery.data?.items ?? [];
  const openAttentionCount = queueQuery.data?.open_attention_count ?? 0;
  const runningCount = queueQuery.data?.running_count ?? 0;
  const pendingCount = queueQuery.data?.pending_count ?? 0;
  const activeCount = runningCount + pendingCount;
  const historyRuns = runsQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const historyTotal = runsQuery.data?.pages[0]?.total ?? historyRuns.length;
  const selectedRunTab =
    searchParams.get("tab") === "history" ? "history" : "active";
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

  function changeRunTab(value: unknown) {
    const next = new URLSearchParams(searchParams.toString());
    if (value === "history") {
      next.set("tab", "history");
    } else {
      next.delete("tab");
      next.delete("attention");
    }
    const query = next.toString();
    router.replace(`/status${query ? `?${query}` : ""}`, { scroll: false });
  }

  if (!mounted) {
    return (
      <p role="status" className="text-sm text-text-secondary">
        상태 정보를 불러오는 중입니다.
      </p>
    );
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

      {runActionFeedback ? (
        <div
          role={runActionFeedback.kind === "error" ? "alert" : "status"}
          className={`rounded-lg border px-3 py-2 text-sm ${
            runActionFeedback.kind === "error"
              ? "border-destructive/30 bg-destructive/5 text-destructive"
              : "border-surface-muted bg-surface-subtle text-text-secondary"
          }`}
        >
          {runActionFeedback.kind === "error" ? (
            <>
              작업 #{runActionFeedback.jobId}의
              {runActionFeedback.action === "stop" ? " 중지" : " 재시작"} 요청에
              실패했습니다: {runActionFeedback.message}
            </>
          ) : runActionFeedback.kind === "stopped" ? (
            <>작업 #{runActionFeedback.jobId}의 중지를 요청했습니다.</>
          ) : (
            <>
              {runActionFeedback.created
                ? "새 재시작 작업을 등록했습니다."
                : "이미 진행 중인 재시작 작업을 사용합니다."}{" "}
              <Link
                href={`/jobs/${runActionFeedback.jobId}`}
                className="font-bold text-primary underline-offset-2 hover:underline"
              >
                작업 보기
              </Link>
            </>
          )}
        </div>
      ) : null}

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={<ListChecksIcon className="size-4" />}
          label="실행 큐"
          value={`실행 ${runningCount} · 대기 ${pendingCount} · 확인 필요 ${openAttentionCount}`}
          tone={
            openAttentionCount > 0
              ? "warn"
              : runningCount > 0
                ? "active"
                : "neutral"
          }
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
            <Tabs value={selectedRunTab} onValueChange={changeRunTab}>
              <TabsList>
                <TabsTrigger value="active">진행 중 {activeCount}</TabsTrigger>
                <TabsTrigger value="history">
                  {attentionOnly ? "확인 필요" : "완료 이력"}{" "}
                  {historyTotal}
                </TabsTrigger>
              </TabsList>
              <TabsContent value="active" className="mt-3">
                {queueQuery.data?.has_more ? (
                  <p role="status" className="mb-2 text-xs text-text-secondary">
                    활성 작업 총 {activeCount}건 중 {queueRuns.length}건 표시
                  </p>
                ) : null}
                <RunStatusTable
                  runs={queueRuns}
                  empty="실행 중이거나 대기 중인 작업이 없습니다."
                  onActionFeedback={setRunActionFeedback}
                />
              </TabsContent>
              <TabsContent value="history" className="mt-3">
                {attentionOnly ? (
                  <div
                    role="status"
                    className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-text-secondary"
                  >
                    <span>아직 확인하지 않은 종료 작업만 표시합니다.</span>
                    <Link
                      href="/status?tab=history"
                      className={buttonVariants({ variant: "outline", size: "xs" })}
                    >
                      전체 이력 보기
                    </Link>
                  </div>
                ) : null}
                <RunStatusTable
                  runs={historyRuns}
                  empty="완료된 작업 이력이 없습니다."
                  onActionFeedback={setRunActionFeedback}
                />
                {runsQuery.isFetchNextPageError ? (
                  <p role="alert" className="mt-2 text-xs text-destructive">
                    다음 작업 이력을 불러오지 못했습니다. 다시 시도해 주세요.
                  </p>
                ) : null}
                {runsQuery.hasNextPage ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="mt-3 w-full"
                    disabled={runsQuery.isFetchingNextPage}
                    onClick={() =>
                      void runsQuery.fetchNextPage({ cancelRefetch: false })
                    }
                  >
                    {runsQuery.isFetchingNextPage
                      ? "작업 이력 불러오는 중"
                      : `다음 작업 이력 불러오기 (${historyRuns.length}/${historyTotal})`}
                  </Button>
                ) : null}
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
  onActionFeedback,
}: {
  runs: CrawlRunSummary[];
  empty: string;
  onActionFeedback: (feedback: RunActionFeedback) => void;
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
            <th className="px-3 py-2 text-right">액션</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.job_id} className="border-t border-surface-muted">
              <td className="px-3 py-2 align-top">
                <div className="flex max-w-36 flex-wrap gap-1">
                  <Badge variant={runOutcomeBadgeVariant(run)}>
                    {runOutcomeLabel(run)}
                  </Badge>
                  {run.attention ? (
                    <Badge variant={runAttentionBadgeVariant(run.attention)}>
                      {runAttentionLabel(run.attention)}
                    </Badge>
                  ) : null}
                </div>
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
                  {run.restart_of_run_id ? (
                    <Link
                      href={`/jobs/${run.restart_of_run_id}`}
                      className="w-fit text-[11px] font-bold text-primary underline-offset-2 hover:underline"
                    >
                      원본 작업 #{run.restart_of_run_id}
                    </Link>
                  ) : null}
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
                      className={runOutcomeProgressBarClass(run)}
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
                <div className="flex flex-col items-end gap-1">
                  <Link
                    href={`/jobs/${run.job_id}`}
                    className={buttonVariants({ variant: "outline", size: "xs" })}
                  >
                    상세
                  </Link>
                  <RunActionButtons run={run} onFeedback={onActionFeedback} />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

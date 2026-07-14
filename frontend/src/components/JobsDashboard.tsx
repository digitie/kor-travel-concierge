"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ListChecksIcon, RefreshCwIcon } from "lucide-react";

import {
  listRunsPage,
  listRunQueue,
  RUN_HISTORY_REFETCH_INTERVAL_MS,
  RUN_QUEUE_OBSERVER_OPTIONS,
  RUN_QUEUE_QUERY_KEY,
  type CrawlRunSummary,
} from "@/lib/api";
import {
  buildRunHistoryParams,
  JOB_HISTORY_STATE_ALL,
  JOB_HISTORY_STATE_OPTIONS,
  JOB_HISTORY_TYPE_ALL,
} from "@/lib/jobs-history";
import {
  categoryDisplayLabel,
  jobTypeDisplayLabel,
  runAttentionBadgeVariant,
  runAttentionLabel,
  runOutcomeBadgeVariant,
  runOutcomeLabel,
  runOutcomeProgressBarClass,
  targetTypeDisplayLabel,
} from "@/lib/display-labels";
import { formatDateTimeShort } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  RunActionButtons,
  type RunActionFeedback,
} from "@/components/RunActionButtons";
import { EmptyState, Panel } from "@/components/panels";

function targetLabel(run: CrawlRunSummary): string {
  return run.target_label ?? run.target_id ?? run.source ?? "-";
}

function progressPercent(run: CrawlRunSummary): string {
  return `${Math.round(run.progress * 100)}%`;
}

export function JobsDashboard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const attentionOnly = searchParams.get("attention") === "open";
  const [stateFilter, setStateFilter] = useState<string>(JOB_HISTORY_STATE_ALL);
  const [typeFilter, setTypeFilter] = useState<string>(JOB_HISTORY_TYPE_ALL);
  const [runActionFeedback, setRunActionFeedback] =
    useState<RunActionFeedback | null>(null);

  const queueQuery = useQuery({
    queryKey: RUN_QUEUE_QUERY_KEY,
    queryFn: listRunQueue,
    ...RUN_QUEUE_OBSERVER_OPTIONS,
  });
  const runsQuery = useInfiniteQuery({
    queryKey: ["runs", "jobs", attentionOnly, stateFilter, typeFilter],
    queryFn: ({ pageParam }) =>
      listRunsPage({
        ...buildRunHistoryParams({
          attentionOnly,
          state: stateFilter,
          jobType: typeFilter,
        }),
        limit: 80,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.next_cursor : undefined,
    staleTime: 60_000,
    refetchInterval: RUN_HISTORY_REFETCH_INTERVAL_MS,
  });

  const queueRuns = queueQuery.data?.items ?? [];
  const runningCount = queueQuery.data?.running_count ?? 0;
  const pendingCount = queueQuery.data?.pending_count ?? 0;
  const activeCount = runningCount + pendingCount;
  const jobTypeOptions = queueQuery.data?.user_job_types ?? [];
  const historyRuns = runsQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const historyTotal = runsQuery.data?.pages[0]?.total ?? historyRuns.length;

  function refresh() {
    void queueQuery.refetch();
    void runsQuery.refetch();
  }

  function setAttention(next: boolean) {
    const params = new URLSearchParams(searchParams.toString());
    if (next) {
      params.set("attention", "open");
    } else {
      params.delete("attention");
    }
    const query = params.toString();
    router.replace(`/jobs${query ? `?${query}` : ""}`, { scroll: false });
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-text-secondary">
          진행 중·대기 작업과 종료된 작업 이력을 한 곳에서 관리합니다.
        </p>
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

      <Panel
        title="진행 중 · 대기"
        icon={<ListChecksIcon className="size-4 text-brand" />}
      >
        {queueQuery.isError ? (
          <p className="mb-2 text-sm text-destructive">
            {queueQuery.error.message}
          </p>
        ) : null}
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
      </Panel>

      <Panel title="작업 이력">
        <div className="mb-3 flex flex-wrap items-center gap-2">
            <Select
              value={stateFilter}
              onValueChange={(value) =>
                setStateFilter(value ?? JOB_HISTORY_STATE_ALL)
              }
            >
              <SelectTrigger className="w-36" aria-label="작업 상태 필터">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {JOB_HISTORY_STATE_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Select
              value={typeFilter}
              onValueChange={(value) =>
                setTypeFilter(value ?? JOB_HISTORY_TYPE_ALL)
              }
            >
              <SelectTrigger className="w-40" aria-label="작업 유형 필터">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value={JOB_HISTORY_TYPE_ALL}>유형 전체</SelectItem>
                  {jobTypeOptions.map((jobType) => (
                    <SelectItem key={jobType} value={jobType}>
                      {jobTypeDisplayLabel(jobType)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button
              type="button"
              size="sm"
              variant={attentionOnly ? "secondary" : "outline"}
              aria-pressed={attentionOnly}
              onClick={() => setAttention(!attentionOnly)}
            >
              확인 필요만
            </Button>
          </div>

          {runsQuery.isError ? (
            <p className="mb-2 text-sm text-destructive">
              {runsQuery.error.message}
            </p>
          ) : null}
          {attentionOnly ? (
            <div
              role="status"
              className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-text-secondary"
            >
              <span>아직 확인하지 않은 종료 작업만 표시합니다.</span>
              <Link
                href="/jobs"
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
              onClick={() => void runsQuery.fetchNextPage({ cancelRefetch: false })}
            >
              {runsQuery.isFetchingNextPage
                ? "작업 이력 불러오는 중"
                : `다음 작업 이력 불러오기 (${historyRuns.length}/${historyTotal})`}
            </Button>
          ) : null}
      </Panel>
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
      <div className="flex items-start">
        <EmptyState>{empty}</EmptyState>
      </div>
    );
  }

  return (
    <div className="max-h-[28rem] overflow-auto rounded-lg border border-surface-muted">
      <table className="w-full min-w-[52rem] text-[13px]">
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

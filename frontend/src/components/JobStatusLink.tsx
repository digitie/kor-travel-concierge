"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ActivityIcon, ListChecksIcon } from "lucide-react";

import {
  listRunQueue,
  RUN_QUEUE_OBSERVER_OPTIONS,
  RUN_QUEUE_QUERY_KEY,
  runQueueRefetchInterval,
  type CrawlRunSummary,
} from "@/lib/api";
import { runStateLabel } from "@/lib/display-labels";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

let previouslyObservedActiveRunIds: Set<string> | null = null;

function targetLabel(run: CrawlRunSummary): string {
  return run.target_label ?? run.target_id ?? run.source ?? "작업";
}

export function JobStatusLink({
  className,
  variant = "full",
}: {
  className?: string;
  variant?: "full" | "menu";
}) {
  const queryClient = useQueryClient();
  const queueQuery = useQuery({
    queryKey: RUN_QUEUE_QUERY_KEY,
    queryFn: listRunQueue,
    ...RUN_QUEUE_OBSERVER_OPTIONS,
    refetchInterval: (query) => runQueueRefetchInterval(query.state),
  });
  const runs = queueQuery.data?.items ?? [];
  const openAttentionCount = queueQuery.data?.open_attention_count ?? 0;
  const runningCount = queueQuery.data?.running_count ?? 0;
  const pendingCount = queueQuery.data?.pending_count ?? 0;
  const activeCount = runningCount + pendingCount;
  const running = runs.filter((run) => run.state.toLowerCase() === "running");
  const pending = runs.filter((run) => run.state.toLowerCase() === "pending");
  const current = running[0] ?? pending[0] ?? null;
  const statusHref =
    openAttentionCount > 0 ? "/jobs?attention=open" : "/jobs";
  const summary = queueQuery.isError
    ? "작업 상태 오류"
    : current
      ? `${runStateLabel(current.state)} · ${targetLabel(current)} · ${
          current.current_message ?? "로그 대기 중"
        }`
      : "유휴 상태";

  useEffect(() => {
    if (!queueQuery.data) return;
    const activeRunIds = new Set(queueQuery.data.items.map((run) => run.job_id));
    const runDisappeared =
      previouslyObservedActiveRunIds != null &&
      [...previouslyObservedActiveRunIds].some(
        (runId) => !activeRunIds.has(runId),
      );
    previouslyObservedActiveRunIds = activeRunIds;
    if (runDisappeared) {
      void queryClient.invalidateQueries({ queryKey: ["destination-facets"] });
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    }
    // 두 poll 사이에 생성과 완료가 모두 일어난 작업은 ID를 관찰하지 못한다. facets의
    // 10분 safety poll과 결과 화면 수동 새로고침이 이 빈틈의 상한을 보장한다.
  }, [queryClient, queueQuery.data]);

  if (variant === "menu") {
    return (
      <Link
        href={statusHref}
        aria-label={`작업 상태: 실행 ${runningCount}, 대기 ${pendingCount}, 확인 필요 ${openAttentionCount}. ${summary}`}
        title={`작업 상태 · 실행 ${runningCount} · 대기 ${pendingCount} · 확인 필요 ${openAttentionCount} · ${summary}`}
        className={cn(
          "inline-flex h-9 min-w-9 shrink-0 items-center justify-center gap-1 rounded-lg border border-surface-muted bg-surface-subtle px-2 text-[12px] font-bold transition-colors hover:border-brand/40 hover:bg-brand-tint",
          className,
        )}
      >
        {current ? (
          <ActivityIcon className="size-3.5 shrink-0 text-brand" />
        ) : (
          <ListChecksIcon className="size-3.5 shrink-0 text-text-secondary" />
        )}
        <span className="tabular-nums text-text-primary">
          {activeCount}
        </span>
        {queueQuery.isError ? (
          <Badge variant="destructive" className="h-5 px-1 text-[10px]">
            오류
          </Badge>
        ) : null}
        {openAttentionCount > 0 ? (
          <Badge variant="destructive" className="h-5 px-1 text-[10px]">
            확인 {openAttentionCount}
          </Badge>
        ) : null}
      </Link>
    );
  }

  return (
    <Link
      href={statusHref}
      aria-label={`작업 상태: 실행 ${runningCount}, 대기 ${pendingCount}, 확인 필요 ${openAttentionCount}. ${summary}`}
      className={cn(
        "inline-flex h-8 min-w-0 max-w-full items-center gap-1.5 rounded-full border border-surface-muted bg-surface-subtle px-2.5 text-[12px] transition-colors hover:border-brand/40 hover:bg-brand-tint",
        className,
      )}
    >
      {current ? (
        <ActivityIcon className="size-3.5 shrink-0 text-brand" />
      ) : (
        <ListChecksIcon className="size-3.5 shrink-0 text-text-secondary" />
      )}
      <span className="shrink-0 font-bold text-text-primary">작업 상태</span>
      <span className="shrink-0 text-text-secondary">
        실행 {runningCount} · 대기 {pendingCount}
      </span>
      {queueQuery.isError ? (
        <Badge variant="destructive" className="h-5 px-1.5 text-[10px]">
          오류
        </Badge>
      ) : null}
      {openAttentionCount > 0 ? (
        <Badge variant="destructive" className="h-5 px-1.5 text-[10px]">
          확인 필요 {openAttentionCount}
        </Badge>
      ) : null}
      <span className="hidden min-w-0 max-w-[18rem] truncate text-text-secondary md:inline">
        · {summary}
      </span>
    </Link>
  );
}

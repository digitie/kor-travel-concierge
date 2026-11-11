"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ActivityIcon, ListChecksIcon } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { Badge } from "@/components/ui/badge";
import {
  listRunQueue,
  RUN_QUEUE_OBSERVER_OPTIONS,
  RUN_QUEUE_QUERY_KEY,
  runQueueRefetchInterval,
} from "@/lib/api";
import { buildRunQueueDisplay } from "@/lib/run-queue-display";
import { cn } from "@/lib/utils";

let previouslyObservedActiveRunIds: Set<string> | null = null;

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
  const {
    openAttentionCount,
    runningCount,
    pendingCount,
    activeCount,
    current,
    statusHref,
    summary,
  } = buildRunQueueDisplay(queueQuery.data, queueQuery.isError);

  useEffect(() => {
    if (!queueQuery.data) return;
    const activeRunIds = new Set(
      queueQuery.data.items.map((run) => run.job_id),
    );
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
          "inline-flex h-control-sm min-w-[1.875rem] shrink-0 items-center justify-center gap-1 rounded-control border border-input bg-transparent px-2 text-xs font-medium no-underline transition-[color,background-color,border-color] duration-fast ease-out hover:border-white/25 hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white",
          className,
        )}
      >
        {current ? (
          <ActivityIcon className="size-3.5 shrink-0 text-brand" />
        ) : (
          <ListChecksIcon className="size-3.5 shrink-0 text-text-secondary" />
        )}
        <span className="tabular-nums text-current">{activeCount}</span>
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
        "inline-flex h-control-sm min-w-0 max-w-full items-center gap-1.5 rounded-control border border-border bg-surface-subtle px-2.5 text-xs transition-[color,background-color,border-color] duration-fast ease-out hover:border-brand hover:bg-brand-tint",
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

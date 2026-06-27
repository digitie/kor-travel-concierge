"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ActivityIcon, ListChecksIcon } from "lucide-react";

import {
  listRunQueue,
  USER_JOB_TYPES,
  type CrawlRunSummary,
} from "@/lib/api";
import { runStateLabel } from "@/lib/display-labels";
import { cn } from "@/lib/utils";

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
  const queueQuery = useQuery({
    queryKey: ["run-queue", "shell"],
    queryFn: () => listRunQueue(USER_JOB_TYPES),
    refetchInterval: 3_000,
  });
  const runs = queueQuery.data ?? [];
  const running = runs.filter((run) => run.state.toLowerCase() === "running");
  const pending = runs.filter((run) => run.state.toLowerCase() === "pending");
  const current = running[0] ?? pending[0] ?? null;
  const summary = queueQuery.isError
    ? "작업 상태 오류"
    : current
      ? `${runStateLabel(current.state)} · ${targetLabel(current)} · ${
          current.current_message ?? "로그 대기 중"
        }`
      : "유휴 상태";

  if (variant === "menu") {
    return (
      <Link
        href="/status"
        aria-label={`작업 상태: 실행 ${running.length}, 대기 ${pending.length}. ${summary}`}
        title={`작업 상태 · 실행 ${running.length} · 대기 ${pending.length}`}
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
          {running.length + pending.length}
        </span>
      </Link>
    );
  }

  return (
    <Link
      href="/status"
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
        실행 {running.length} · 대기 {pending.length}
      </span>
      <span className="hidden min-w-0 max-w-[18rem] truncate text-text-secondary md:inline">
        · {summary}
      </span>
    </Link>
  );
}

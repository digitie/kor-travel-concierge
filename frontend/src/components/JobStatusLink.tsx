"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ActivityIcon, ListChecksIcon } from "lucide-react";

import {
  listRunQueue,
  USER_JOB_TYPES,
  type CrawlRunSummary,
} from "@/lib/api";
import { cn } from "@/lib/utils";

function targetLabel(run: CrawlRunSummary): string {
  return run.target_label ?? run.target_id ?? run.source ?? "작업";
}

function stateLabel(state: string): string {
  if (state === "running") return "실행";
  if (state === "pending") return "대기";
  if (state === "failed") return "실패";
  if (state === "done") return "완료";
  return state;
}

export function JobStatusLink({ className }: { className?: string }) {
  const queueQuery = useQuery({
    queryKey: ["run-queue", "shell"],
    queryFn: () => listRunQueue(USER_JOB_TYPES),
    refetchInterval: 3_000,
  });
  const runs = queueQuery.data ?? [];
  const running = runs.filter((run) => run.state === "running");
  const pending = runs.filter((run) => run.state === "pending");
  const current = running[0] ?? pending[0] ?? null;

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
        ·{" "}
        {queueQuery.isError
          ? "오류"
          : current
            ? `${stateLabel(current.state)} · ${targetLabel(current)} · ${
                current.current_message ?? "로그 대기 중"
              }`
            : "유휴 상태"}
      </span>
    </Link>
  );
}

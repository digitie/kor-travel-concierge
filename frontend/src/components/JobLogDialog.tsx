"use client";

import type { RunStatusLog } from "@/lib/api";
import { runStateBadgeVariant, runStateLabel } from "@/lib/display-labels";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { CopyButton } from "@/components/CopyButton";

// 수집 상태 로그·오류를 전체로 보여주고 복사할 수 있는 공용 다이얼로그.
// HarvestConsole(수집 패널)과 JobDetailDialog(작업 상세) 양쪽에서 재사용한다.

export type JobLogLike = {
  job_id?: string | null;
  state: string;
  current_message: string | null;
  last_error: string | null;
  status_logs: RunStatusLog[];
};

function formatLogTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function buildJobReport(status: JobLogLike): string {
  const lines = [
    "[작업 정보]",
    `job_id: ${status.job_id ?? "-"}`,
    `상태: ${runStateLabel(status.state)}`,
    `현재 메시지: ${status.current_message ?? "-"}`,
    `오류: ${status.last_error ?? "-"}`,
    "",
    `[상태 로그] (${status.status_logs.length})`,
    ...status.status_logs.map(
      (log) => `${log.timestamp} [${log.level}] ${log.message}`,
    ),
  ];
  return lines.join("\n");
}

export function JobLogView({ status }: { status: JobLogLike }) {
  return (
    <div className="flex flex-col gap-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <Badge variant={runStateBadgeVariant(status.state)}>
          {runStateLabel(status.state)}
        </Badge>
        <CopyButton text={buildJobReport(status)} label="전체 복사" />
      </div>

      {status.current_message ? (
        <div className="flex flex-col gap-1">
          <p className="text-xs text-muted-foreground">현재 메시지</p>
          <p className="break-words whitespace-pre-wrap">
            {status.current_message}
          </p>
        </div>
      ) : null}

      {status.last_error ? (
        <div className="flex flex-col gap-1 rounded-lg border border-destructive/40 bg-destructive/5 p-2">
          <p className="text-xs font-semibold text-destructive">오류 상세</p>
          <pre className="max-h-48 overflow-auto break-words whitespace-pre-wrap text-xs text-destructive">
            {status.last_error}
          </pre>
        </div>
      ) : null}

      <div className="flex flex-col gap-1">
        <p className="text-xs text-muted-foreground">
          상태 로그 ({status.status_logs.length})
        </p>
        <div className="flex max-h-72 flex-col gap-1.5 overflow-y-auto rounded-lg border p-2">
          {status.status_logs.length === 0 ? (
            <p className="text-xs text-muted-foreground">로그가 없습니다.</p>
          ) : (
            status.status_logs.map((log, index) => (
              <div key={index} className="flex flex-col gap-0.5 text-xs">
                <span className="text-muted-foreground">
                  {formatLogTime(log.timestamp)} · {log.level}
                </span>
                <span className="break-words whitespace-pre-wrap">
                  {log.message}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export function JobLogDialog({
  status,
  title,
  onClose,
}: {
  status: JobLogLike | null;
  title?: string;
  onClose: () => void;
}) {
  return (
    <Dialog open={Boolean(status)} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title ?? "작업 로그·오류"}</DialogTitle>
          <DialogDescription>
            전체 상태 로그와 오류 메시지
          </DialogDescription>
        </DialogHeader>
        {status ? <JobLogView status={status} /> : null}
      </DialogContent>
    </Dialog>
  );
}

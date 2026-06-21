"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLinkIcon } from "lucide-react";

import {
  getRunVideos,
  getSourceTargetVideos,
  type CrawlRunSummary,
  type SourceTargetSummary,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

function intervalLabel(minutes: number | null | undefined): string {
  if (!minutes) return "-";
  if (minutes % 43200 === 0) return `${minutes / 43200}달`;
  if (minutes % 10080 === 0) return `${minutes / 10080}주일`;
  if (minutes % 1440 === 0) return `${minutes / 1440}일`;
  if (minutes % 60 === 0) return `${minutes / 60}시간`;
  return `${minutes}분`;
}
function targetTypeLabel(type: string | null | undefined): string {
  if (type === "channel") return "채널";
  if (type === "playlist") return "재생목록";
  if (type === "keyword") return "검색어";
  if (type === "video") return "영상";
  return type ?? "-";
}
function durationLabel(seconds: number | null): string {
  if (seconds == null) return "-";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}분 ${s}초` : `${s}초`;
}

export function JobDetailDialog({
  run,
  target,
  onClose,
}: {
  run?: CrawlRunSummary | null;
  target?: SourceTargetSummary | null;
  onClose: () => void;
}) {
  const open = Boolean(run || target);
  const videosQuery = useQuery({
    queryKey: ["job-videos", run?.job_id ?? null, target?.id ?? null],
    queryFn: () =>
      run ? getRunVideos(run.job_id) : getSourceTargetVideos(target!.id),
    enabled: open,
  });
  const videos = videosQuery.data ?? [];

  const result = (run?.result ?? {}) as Record<string, unknown>;
  const fields: { label: string; value: string }[] = run
    ? [
        { label: "작업", value: `${run.job_type} · #${run.job_id}` },
        { label: "상태", value: run.state },
        { label: "대상 유형", value: targetTypeLabel(run.target_type) },
        { label: "키워드/ID", value: run.target_id ?? "-" },
        {
          label: "최대 영상 수",
          value: String((result.max_videos as number) ?? "-"),
        },
        {
          label: "수집/신규",
          value: `${(result.discovered as number) ?? "-"} / ${
            (result.inserted as number) ?? "-"
          }`,
        },
      ]
    : target
      ? [
          { label: "대상 유형", value: targetTypeLabel(target.target_type) },
          { label: "키워드/ID", value: target.source_value },
          { label: "반복 간격", value: intervalLabel(target.scan_interval_minutes) },
          {
            label: "반복 횟수",
            value: target.max_runs === 0 ? "무한" : String(target.max_runs),
          },
          { label: "실행 횟수", value: String(target.run_count) },
          { label: "활성", value: target.is_active ? "예" : "아니오" },
        ]
      : [];

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>작업 상세</DialogTitle>
          <DialogDescription>
            {run
              ? "1회성 작업의 입력값·결과·수집 영상"
              : "반복 작업의 설정과 그동안 수집한 영상"}
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {fields.map((field) => (
            <div
              key={field.label}
              className="flex flex-col gap-0.5 rounded-lg border p-2.5"
            >
              <span className="text-xs text-muted-foreground">{field.label}</span>
              <span className="truncate text-sm font-medium">{field.value}</span>
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-2 border-t pt-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium">누적 수집 영상</p>
            <Badge variant="secondary">{videos.length}</Badge>
          </div>
          {videosQuery.isLoading ? (
            <p className="text-xs text-muted-foreground">불러오는 중…</p>
          ) : videos.length === 0 ? (
            <p className="rounded-lg border p-2 text-xs text-muted-foreground">
              수집된 영상이 없습니다.
            </p>
          ) : (
            <div className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
              {videos.map((video) => (
                <a
                  key={video.video_id}
                  href={video.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex flex-col gap-0.5 rounded-lg border p-2 text-xs transition-colors hover:bg-muted"
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{video.title}</span>
                    <ExternalLinkIcon className="size-3 shrink-0 text-muted-foreground" />
                  </span>
                  <span className="truncate text-muted-foreground">
                    {[
                      video.channel_title,
                      durationLabel(video.duration_seconds),
                      video.published_at?.slice(0, 10),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </a>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

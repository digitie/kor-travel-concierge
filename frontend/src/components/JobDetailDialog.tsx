"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ExternalLinkIcon } from "lucide-react";

import {
  getRunPlaces,
  getRunVideos,
  getSourceTargetVideos,
  type CrawlRunSummary,
  type RunPlace,
  type SourceTargetSummary,
} from "@/lib/api";
import { JobLogView } from "@/components/JobLogDialog";
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
  if (type === "channel") return "유튜버";
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
  const router = useRouter();
  const placesQuery = useQuery({
    queryKey: ["job-places", run?.job_id ?? null],
    queryFn: () => getRunPlaces(run!.job_id),
    enabled: open && Boolean(run),
  });
  const places = placesQuery.data ?? [];

  // POI 클릭: 확정 장소는 결과 뷰로, 검수 대기 후보는 검수 뷰로 이동(딥링크).
  function openPlace(place: RunPlace) {
    if (place.status === "confirmed" && place.place_id != null) {
      router.push(`/?place=${place.place_id}`);
    } else if (place.candidate_id != null) {
      router.push(`/review?candidate=${place.candidate_id}`);
    }
    onClose();
  }

  const result = (run?.result ?? {}) as Record<string, unknown>;
  const fields: { label: string; value: string }[] = run
    ? [
        {
          label: "대상 유형",
          value: run.target_type_label ?? targetTypeLabel(run.target_type),
        },
        { label: "대상", value: run.target_label ?? run.target_id ?? "-" },
        { label: "작업 유형", value: run.job_type_label ?? run.job_type },
        { label: "상태", value: run.state },
        { label: "진행률", value: `${Math.round((run.progress ?? 0) * 100)}%` },
        {
          label: "최대 영상 수",
          value: run.max_videos != null ? String(run.max_videos) : "-",
        },
        {
          // result는 완료 시에만 채워지므로 진행 중에는 "진행 중"으로 표기한다.
          label: "수집/신규",
          value: run.result
            ? `${(result.discovered as number) ?? "-"} / ${
                (result.inserted as number) ?? "-"
              }`
            : "진행 중",
        },
        { label: "현재 메시지", value: run.current_message ?? "-" },
      ]
    : target
      ? [
          {
            label: "대상 유형",
            value:
              target.target_type_label ?? targetTypeLabel(target.target_type),
          },
          {
            label: "대상",
            value:
              target.target_label ??
              target.display_name ??
              target.source_value,
          },
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
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
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

        {run ? (
          <div className="flex flex-col gap-2 border-t pt-4">
            <p className="text-sm font-medium">상태 로그·오류</p>
            <JobLogView status={run} />
          </div>
        ) : null}

        {run ? (
          <div className="flex flex-col gap-2 border-t pt-4">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium">추출된 POI</p>
              <Badge variant="secondary">{places.length}</Badge>
            </div>
            {placesQuery.isLoading ? (
              <p className="text-xs text-muted-foreground">불러오는 중…</p>
            ) : places.length === 0 ? (
              <p className="rounded-lg border p-2 text-xs text-muted-foreground">
                추출된 POI가 없습니다.
              </p>
            ) : (
              <div className="flex max-h-60 flex-col gap-1.5 overflow-y-auto">
                {places.map((place) => (
                  <button
                    key={`${place.kind}-${place.place_id ?? place.candidate_id}`}
                    type="button"
                    onClick={() => openPlace(place)}
                    title={
                      place.status === "confirmed"
                        ? "결과 뷰로 이동"
                        : "검수 뷰로 이동"
                    }
                    className="flex items-center justify-between gap-2 rounded-lg border p-2 text-left text-xs transition-colors hover:border-primary hover:bg-muted"
                  >
                    <span className="truncate font-medium">{place.name}</span>
                    <span className="flex shrink-0 items-center gap-1">
                      {place.is_domestic === false ? (
                        <Badge variant="outline">해외</Badge>
                      ) : null}
                      <Badge
                        variant={
                          place.status === "confirmed" ? "secondary" : "outline"
                        }
                      >
                        {place.status === "confirmed" ? "확정" : "검수 대기"}
                      </Badge>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : null}

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

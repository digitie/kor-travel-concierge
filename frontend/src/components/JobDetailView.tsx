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
import {
  categoryDisplayLabel,
  jobTypeDisplayLabel,
  runStateLabel,
  targetTypeDisplayLabel,
} from "@/lib/display-labels";
import { JobLogView } from "@/components/JobLogDialog";
import { Badge } from "@/components/ui/badge";

export function intervalLabel(minutes: number | null | undefined): string {
  if (!minutes) return "-";
  if (minutes % 43200 === 0) return `${minutes / 43200}달`;
  if (minutes % 10080 === 0) return `${minutes / 10080}주일`;
  if (minutes % 1440 === 0) return `${minutes / 1440}일`;
  if (minutes % 60 === 0) return `${minutes / 60}시간`;
  return `${minutes}분`;
}
export function targetTypeLabel(type: string | null | undefined): string {
  return targetTypeDisplayLabel(type);
}
export function durationLabel(seconds: number | null): string {
  if (seconds == null) return "-";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}분 ${s}초` : `${s}초`;
}
function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
function runResultLabel(result: Record<string, unknown>, hasResult: boolean): string {
  if (!hasResult) return "진행 중";
  const parts: string[] = [];
  if (typeof result.discovered === "number") parts.push(`수집 ${result.discovered}`);
  if (typeof result.inserted === "number") parts.push(`신규 ${result.inserted}`);
  if (typeof result.updated === "number") parts.push(`갱신 ${result.updated}`);
  if (typeof result.skipped === "number") parts.push(`건너뜀 ${result.skipped}`);
  if (typeof result.enqueued_jobs === "number") {
    parts.push(`등록 ${result.enqueued_jobs}`);
  }
  return parts.length > 0 ? parts.join(" · ") : "결과 기록 있음";
}

// 작업 상세 본문(필드·상태로그·추출 POI·수집 영상). 다이얼로그와 별도 페이지(/jobs/[id])
// 양쪽에서 재사용한다. `hideVideos`면 수집 영상 섹션을 숨긴다(페이지가 더 상세한
// 영상별 섹션을 따로 렌더할 때).
export function JobDetailView({
  run,
  target,
  hideVideos,
  onNavigate,
}: {
  run?: CrawlRunSummary | null;
  target?: SourceTargetSummary | null;
  hideVideos?: boolean;
  onNavigate?: () => void;
}) {
  const open = Boolean(run || target);
  const router = useRouter();
  const videosQuery = useQuery({
    queryKey: ["job-videos", run?.job_id ?? null, target?.id ?? null],
    queryFn: () =>
      run ? getRunVideos(run.job_id) : getSourceTargetVideos(target!.id),
    enabled: open && !hideVideos,
  });
  const videos = videosQuery.data ?? [];
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
    onNavigate?.();
  }

  const result = (run?.result ?? {}) as Record<string, unknown>;
  const fields: { label: string; value: string }[] = run
    ? [
        {
          label: "기본 카테고리",
          value: categoryDisplayLabel(
            run.default_category_label ?? run.default_category_code,
          ),
        },
        {
          label: "최대 영상 수",
          value: run.max_videos != null ? String(run.max_videos) : "-",
        },
        { label: "재시도", value: `${run.retry_count}회` },
        {
          label: "결과",
          value: runResultLabel(result, Boolean(run.result)),
        },
        { label: "등록", value: formatDateTime(run.created_at) },
        { label: "시작", value: formatDateTime(run.started_at) },
        { label: "종료", value: formatDateTime(run.finished_at) },
        { label: "현재 메시지", value: run.current_message ?? "-" },
        { label: "오류", value: run.last_error ?? "-" },
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
          {
            label: "기본 카테고리",
            value: categoryDisplayLabel(
              target.default_category_label ?? target.default_category_code,
            ),
          },
          { label: "반복 간격", value: intervalLabel(target.scan_interval_minutes) },
          {
            label: "반복 횟수",
            value: target.max_runs === 0 ? "무한" : String(target.max_runs),
          },
          { label: "실행 횟수", value: String(target.run_count) },
          { label: "활성", value: target.is_active ? "예" : "아니오" },
          { label: "다음 실행", value: formatDateTime(target.next_crawl_at) },
          { label: "최근 실행", value: formatDateTime(target.last_crawled_at) },
          { label: "최근 스캔", value: formatDateTime(target.last_scan_at) },
          { label: "최근 오류", value: target.last_scan_error ?? "-" },
        ]
      : [];

  return (
    <div className="flex flex-col gap-4">
      {run ? (
        <RunOverview run={run} result={result} />
      ) : target ? (
        <TargetOverview target={target} />
      ) : null}

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
        {fields.map((field) => (
          <div
            key={field.label}
            className="flex min-w-0 flex-col gap-0.5 rounded-lg border border-surface-muted bg-surface-subtle p-2.5"
          >
            <span className="text-xs text-muted-foreground">{field.label}</span>
            <span className="break-words text-sm font-medium">{field.value}</span>
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

      {!hideVideos ? (
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
      ) : null}
    </div>
  );
}

function RunOverview({
  run,
  result,
}: {
  run: CrawlRunSummary;
  result: Record<string, unknown>;
}) {
  const progress = Math.round((run.progress ?? 0) * 100);
  const targetName = run.target_label ?? run.target_id ?? "-";
  return (
    <section className="rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <Badge variant={runStateVariant(run.state)}>
              {runStateLabel(run.state)}
            </Badge>
            <Badge variant="outline">
              {run.job_type_label ?? jobTypeDisplayLabel(run.job_type)}
            </Badge>
            <Badge variant="outline">
              {run.target_type_label ?? targetTypeLabel(run.target_type)}
            </Badge>
          </div>
          <h2 className="break-words text-[18px] font-bold leading-snug">
            {targetName}
          </h2>
          <p className="mt-2 line-clamp-2 text-[13px] text-text-secondary">
            {run.last_error ?? run.current_message ?? runResultLabel(result, Boolean(run.result))}
          </p>
        </div>
        <div className="w-full shrink-0 lg:w-72">
          <div className="mb-1 flex items-center justify-between text-[12px]">
            <span className="font-medium text-text-secondary">진행률</span>
            <span className="font-bold tabular-nums">{progress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-muted">
            <div
              className={progressBarClass(run.state)}
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-[12px] text-text-secondary">
            <span>시작 {formatDateTime(run.started_at)}</span>
            <span>종료 {formatDateTime(run.finished_at)}</span>
          </div>
        </div>
      </div>
    </section>
  );
}

function TargetOverview({ target }: { target: SourceTargetSummary }) {
  const targetName = target.target_label ?? target.display_name ?? target.source_value;
  return (
    <section className="rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant={target.is_active ? "secondary" : "outline"}>
          {target.is_active ? "활성" : "중지"}
        </Badge>
        <Badge variant="outline">
          {target.target_type_label ?? targetTypeLabel(target.target_type)}
        </Badge>
      </div>
      <h2 className="mt-2 break-words text-[18px] font-bold leading-snug">
        {targetName}
      </h2>
      <p className="mt-2 text-[13px] text-text-secondary">
        다음 실행 {formatDateTime(target.next_crawl_at)} · 최근 실행{" "}
        {formatDateTime(target.last_crawled_at)}
      </p>
    </section>
  );
}

function runStateVariant(
  state: string,
): "outline" | "secondary" | "destructive" {
  const normalized = state.toLowerCase();
  if (normalized === "failed") return "destructive";
  if (normalized === "running" || normalized === "done") return "secondary";
  return "outline";
}

function progressBarClass(state: string) {
  const normalized = state.toLowerCase();
  if (normalized === "failed") return "h-full rounded-full bg-destructive";
  if (normalized === "done") return "h-full rounded-full bg-success";
  return "h-full rounded-full bg-primary";
}

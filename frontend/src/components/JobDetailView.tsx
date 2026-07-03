"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2Icon,
  ExternalLinkIcon,
  ListChecksIcon,
  MapPinIcon,
  TimerIcon,
} from "lucide-react";

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
  runProgressBarClass,
  runStateBadgeVariant,
  runStateLabel,
  targetTypeDisplayLabel,
} from "@/lib/display-labels";
import { durationLabel, formatDateTime, intervalLabel } from "@/lib/format";
import { JobLogView } from "@/components/JobLogDialog";
import { Badge } from "@/components/ui/badge";
import { EmptyState, MetricCard, Panel, Section } from "@/components/panels";

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
  variant = "compact",
}: {
  run?: CrawlRunSummary | null;
  target?: SourceTargetSummary | null;
  hideVideos?: boolean;
  onNavigate?: () => void;
  variant?: "compact" | "page";
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
        { label: "재시도", value: `${run.retry_count}회` },
        { label: "등록", value: formatDateTime(run.created_at) },
        { label: "시작", value: formatDateTime(run.started_at) },
        { label: "종료", value: formatDateTime(run.finished_at) },
      ]
    : target
      ? [
          {
            label: "대상 유형",
            value:
              target.target_type_label ?? targetTypeDisplayLabel(target.target_type),
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
  const detailGridClass =
    variant === "page"
      ? "grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]"
      : "grid gap-4";

  return (
    <div className="flex flex-col gap-5">
      {run ? (
        <RunSummaryCards run={run} result={result} placesCount={places.length} />
      ) : target ? (
        <TargetSummaryCards target={target} videosCount={videos.length} />
      ) : null}

      <Section title={run ? "작업" : "반복 작업"}>
        <section className={detailGridClass}>
          {run ? (
            <RunProgressPanel run={run} result={result} />
          ) : target ? (
            <TargetProgressPanel target={target} />
          ) : null}
          <Panel title="세부 정보">
            <MetricGrid fields={fields} singleColumn={variant === "page"} />
          </Panel>
        </section>
      </Section>

      {run ? (
        <Section title="로그와 결과">
          <section className={detailGridClass}>
            <Panel title="상태 로그·오류">
              <JobLogView status={run} />
            </Panel>
            <Panel title="추출된 POI">
              <RunPlacesTable
                places={places}
                isLoading={placesQuery.isLoading}
                onOpenPlace={openPlace}
              />
            </Panel>
          </section>
        </Section>
      ) : null}

      {!hideVideos ? (
        <Section title="수집 영상">
          <Panel title="누적 수집 영상">
            <CollectedVideosTable
              videos={videos}
              isLoading={videosQuery.isLoading}
            />
          </Panel>
        </Section>
      ) : null}
    </div>
  );
}

function RunSummaryCards({
  run,
  result,
  placesCount,
}: {
  run: CrawlRunSummary;
  result: Record<string, unknown>;
  placesCount: number;
}) {
  const progress = Math.round((run.progress ?? 0) * 100);
  return (
    <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        icon={<ListChecksIcon className="size-4" />}
        label="상태"
        value={runStateLabel(run.state)}
        tone={run.state.toLowerCase() === "failed" ? "warn" : "neutral"}
      />
      <MetricCard
        icon={<TimerIcon className="size-4" />}
        label="진행률"
        value={`${progress}%`}
        tone={run.state.toLowerCase() === "running" ? "active" : "neutral"}
      />
      <MetricCard
        icon={<CheckCircle2Icon className="size-4" />}
        label="결과"
        value={runResultLabel(result, Boolean(run.result))}
      />
      <MetricCard
        icon={<MapPinIcon className="size-4" />}
        label="추출 POI"
        value={`${placesCount.toLocaleString()}개`}
      />
    </section>
  );
}

function TargetSummaryCards({
  target,
  videosCount,
}: {
  target: SourceTargetSummary;
  videosCount: number;
}) {
  return (
    <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        icon={<ListChecksIcon className="size-4" />}
        label="상태"
        value={target.is_active ? "활성" : "중지"}
        tone={target.is_active ? "active" : "neutral"}
      />
      <MetricCard
        icon={<TimerIcon className="size-4" />}
        label="반복 간격"
        value={intervalLabel(target.scan_interval_minutes)}
      />
      <MetricCard
        icon={<CheckCircle2Icon className="size-4" />}
        label="실행 횟수"
        value={`${target.run_count.toLocaleString()}회`}
      />
      <MetricCard
        icon={<MapPinIcon className="size-4" />}
        label="수집 영상"
        value={`${videosCount.toLocaleString()}개`}
      />
    </section>
  );
}

function RunProgressPanel({
  run,
  result,
}: {
  run: CrawlRunSummary;
  result: Record<string, unknown>;
}) {
  const progress = Math.round((run.progress ?? 0) * 100);
  const targetName = run.target_label ?? run.target_id ?? "-";
  return (
    <Panel title="대상과 진행">
      <div className="flex min-w-0 flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <Badge variant={runStateBadgeVariant(run.state)}>
              {runStateLabel(run.state)}
            </Badge>
            <Badge variant="outline">
              {run.job_type_label ?? jobTypeDisplayLabel(run.job_type)}
            </Badge>
            <Badge variant="outline">
              {run.target_type_label ?? targetTypeDisplayLabel(run.target_type)}
            </Badge>
          </div>
          <h2 className="break-words text-[18px] font-bold leading-snug">
            {targetName}
          </h2>
          <p className="mt-2 line-clamp-2 text-[13px] text-text-secondary">
            {run.last_error ?? run.current_message ?? runResultLabel(result, Boolean(run.result))}
          </p>
          <p className="mt-2 break-all font-mono text-[11px] text-text-secondary">
            {run.job_id}
          </p>
        </div>
        <div className="w-full shrink-0 lg:w-72">
          <div className="mb-1 flex items-center justify-between text-[12px]">
            <span className="font-medium text-text-secondary">진행률</span>
            <span className="font-bold tabular-nums">{progress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-muted">
            <div
              className={runProgressBarClass(run.state)}
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 text-[12px] text-text-secondary">
            <span>시작 {formatDateTime(run.started_at)}</span>
            <span>종료 {formatDateTime(run.finished_at)}</span>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function TargetProgressPanel({ target }: { target: SourceTargetSummary }) {
  const targetName = target.target_label ?? target.display_name ?? target.source_value;
  return (
    <Panel title="대상과 일정">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant={target.is_active ? "secondary" : "outline"}>
          {target.is_active ? "활성" : "중지"}
        </Badge>
        <Badge variant="outline">
          {target.target_type_label ?? targetTypeDisplayLabel(target.target_type)}
        </Badge>
      </div>
      <h2 className="mt-2 break-words text-[18px] font-bold leading-snug">
        {targetName}
      </h2>
      <p className="mt-2 text-[13px] text-text-secondary">
        다음 실행 {formatDateTime(target.next_crawl_at)} · 최근 실행{" "}
        {formatDateTime(target.last_crawled_at)}
      </p>
    </Panel>
  );
}

function RunPlacesTable({
  places,
  isLoading,
  onOpenPlace,
}: {
  places: RunPlace[];
  isLoading: boolean;
  onOpenPlace: (place: RunPlace) => void;
}) {
  if (isLoading) return <EmptyState>불러오는 중...</EmptyState>;
  if (places.length === 0) return <EmptyState>추출된 POI가 없습니다.</EmptyState>;

  return (
    <div className="max-h-72 overflow-auto rounded-lg border border-surface-muted">
      <table className="w-full min-w-[34rem] text-[13px]">
        <thead className="sticky top-0 z-10 bg-surface-subtle text-left text-[12px] font-bold text-text-secondary">
          <tr>
            <th className="px-3 py-2">장소</th>
            <th className="px-3 py-2">상태</th>
            <th className="px-3 py-2 text-right">이동</th>
          </tr>
        </thead>
        <tbody>
          {places.map((place) => (
            <tr
              key={`${place.kind}-${place.place_id ?? place.candidate_id}`}
              className="border-t border-surface-muted"
            >
              <td className="px-3 py-2 align-top">
                <span className="line-clamp-2 font-medium">{place.name}</span>
              </td>
              <td className="px-3 py-2 align-top">
                <div className="flex flex-wrap gap-1">
                  {place.is_domestic === false ? (
                    <Badge variant="outline">해외</Badge>
                  ) : null}
                  <Badge
                    variant={place.status === "confirmed" ? "secondary" : "outline"}
                  >
                    {place.status === "confirmed" ? "확정" : "검수 대기"}
                  </Badge>
                </div>
              </td>
              <td className="px-3 py-2 align-top">
                <button
                  type="button"
                  onClick={() => onOpenPlace(place)}
                  className="ml-auto block text-[12px] font-medium text-primary hover:underline"
                >
                  {place.status === "confirmed" ? "결과" : "검수"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CollectedVideosTable({
  videos,
  isLoading,
}: {
  videos: {
    video_id: string;
    title: string;
    url: string;
    channel_title?: string | null;
    duration_seconds: number | null;
    published_at?: string | null;
  }[];
  isLoading: boolean;
}) {
  if (isLoading) return <EmptyState>불러오는 중...</EmptyState>;
  if (videos.length === 0) return <EmptyState>수집된 영상이 없습니다.</EmptyState>;

  return (
    <div className="max-h-80 overflow-auto rounded-lg border border-surface-muted">
      <table className="w-full min-w-[42rem] text-[13px]">
        <thead className="sticky top-0 z-10 bg-surface-subtle text-left text-[12px] font-bold text-text-secondary">
          <tr>
            <th className="px-3 py-2">영상</th>
            <th className="px-3 py-2">채널</th>
            <th className="px-3 py-2">길이</th>
            <th className="px-3 py-2">공개일</th>
          </tr>
        </thead>
        <tbody>
          {videos.map((video) => (
            <tr key={video.video_id} className="border-t border-surface-muted">
              <td className="px-3 py-2 align-top">
                <a
                  href={video.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex min-w-0 items-start gap-1 font-medium"
                >
                  <span className="line-clamp-2">{video.title}</span>
                  <ExternalLinkIcon className="mt-0.5 size-3 shrink-0 text-muted-foreground" />
                </a>
                <span className="font-mono text-[11px] text-text-secondary">
                  {video.video_id}
                </span>
              </td>
              <td className="px-3 py-2 align-top text-text-secondary">
                {video.channel_title ?? "-"}
              </td>
              <td className="px-3 py-2 align-top text-text-secondary">
                {durationLabel(video.duration_seconds)}
              </td>
              <td className="px-3 py-2 align-top text-text-secondary">
                {video.published_at?.slice(0, 10) ?? "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MetricGrid({
  fields,
  singleColumn,
}: {
  fields: { label: string; value: string }[];
  singleColumn?: boolean;
}) {
  return (
    <div className={`grid gap-2 ${singleColumn ? "grid-cols-1" : "grid-cols-2"}`}>
      {fields.map((field) => (
        <div
          key={field.label}
          className="flex min-w-0 flex-col gap-0.5 rounded-lg border border-surface-muted bg-surface-subtle p-2.5"
        >
          <span className="text-[12px] text-text-secondary">{field.label}</span>
          <span className="break-words text-[13px] font-bold">{field.value}</span>
        </div>
      ))}
    </div>
  );
}

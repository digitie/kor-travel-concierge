"use client";

import type { ReactNode } from "react";
import Link from "next/link";
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
  runAttentionBadgeVariant,
  runAttentionLabel,
  runOutcome,
  runOutcomeBadgeVariant,
  runOutcomeLabel,
  runOutcomeProgressBarClass,
  targetTypeDisplayLabel,
} from "@/lib/display-labels";
import { durationLabel, formatDateTime, intervalLabel } from "@/lib/format";
import { JobLogView } from "@/components/JobLogDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, MetricCard, Panel, Section } from "@/components/panels";

function runResultLabel(result: Record<string, unknown>, hasResult: boolean): string {
  if (!hasResult) return "진행 중";
  if (result.quota_deferred === true) return "쿼터로 처리 보류";
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

function queryErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function DataLoadError({
  error,
  fallback,
  onRetry,
}: {
  error: unknown;
  fallback: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-control border border-destructive bg-destructive-tint p-3 text-sm text-destructive"
    >
      <p className="font-semibold">{fallback}</p>
      <pre className="max-h-40 overflow-auto break-words whitespace-pre-wrap text-xs">
        {queryErrorMessage(error, fallback)}
      </pre>
      {onRetry ? (
        <Button
          type="button"
          size="xs"
          variant="outline"
          className="w-fit border-destructive text-destructive hover:bg-destructive/10"
          onClick={onRetry}
        >
          다시 시도
        </Button>
      ) : null}
    </div>
  );
}

// 작업 상세 본문(필드·상태로그·추출 POI·수집 영상). 다이얼로그와 별도 페이지(/jobs/[id])
// 양쪽에서 재사용한다. `hideVideos`면 수집 영상 섹션을 숨긴다(페이지가 더 상세한
// 영상별 섹션을 따로 렌더할 때).
export function JobDetailView({
  run,
  target,
  hideVideos,
  hideLog,
  afterDetails,
  onNavigate,
  variant = "compact",
}: {
  run?: CrawlRunSummary | null;
  target?: SourceTargetSummary | null;
  hideVideos?: boolean;
  // 로그를 화면 맨 아래로 옮기고 싶은 페이지가 직접 렌더할 수 있도록 여기서는
  // 숨긴다(JobLogView는 계속 export해 재사용한다).
  hideLog?: boolean;
  // "작업"(진행·세부 정보) 섹션 바로 다음, "추출된 POI"/로그 앞에 끼워 넣을 내용.
  // 중요도가 높은 섹션(예: 영상 처리)을 위로 올리고 싶은 페이지가 쓴다.
  afterDetails?: ReactNode;
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
  const fields: { label: string; value: string; wrap?: boolean }[] = run
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
            // 검색어/제목처럼 길이가 정해지지 않은 값 — 한 줄로 자르면 실제 대상을
            // 알아볼 수 없게 될 수 있어 줄바꿈을 허용한다.
            wrap: true,
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
          {
            label: "최근 오류",
            value: target.last_scan_error ?? "-",
            // 오류 메시지는 길 수 있어(한 줄 자르기+hover title은 터치 기기에서
            // 확인할 방법이 없다) 줄바꿈을 허용한다.
            wrap: true,
          },
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

      {afterDetails}

      {run && hideLog ? (
        // 로그는 이 화면에서 숨기고(호출부가 맨 아래에 직접 배치), 추출된 POI만 둔다.
        <Section title="추출된 POI">
          <Panel title="추출된 POI">
            <RunPlacesTable
              places={places}
              isLoading={placesQuery.isLoading}
              error={placesQuery.error}
              onRetry={() => void placesQuery.refetch()}
              onOpenPlace={openPlace}
            />
          </Panel>
        </Section>
      ) : run ? (
        <Section title="로그와 결과">
          <section className={detailGridClass}>
            <Panel title="상태 로그·오류">
              <JobLogView status={run} />
            </Panel>
            <Panel title="추출된 POI">
              <RunPlacesTable
                places={places}
                isLoading={placesQuery.isLoading}
                error={placesQuery.error}
                onRetry={() => void placesQuery.refetch()}
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
              error={videosQuery.error}
              onRetry={() => void videosQuery.refetch()}
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
  const outcome = runOutcome(run);
  return (
    <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        icon={<ListChecksIcon className="size-4" />}
        label="상태"
        value={runOutcomeLabel(run)}
        tone={
          outcome === "failed" || outcome === "quota_deferred"
            ? "warn"
            : "neutral"
        }
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
            <Badge variant={runOutcomeBadgeVariant(run)}>
              {runOutcomeLabel(run)}
            </Badge>
            {run.attention ? (
              <Badge variant={runAttentionBadgeVariant(run.attention)}>
                {runAttentionLabel(run.attention)}
              </Badge>
            ) : null}
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
          {run.restart_of_run_id ? (
            <Link
              href={`/jobs/${run.restart_of_run_id}`}
              className="mt-1 inline-flex text-[12px] font-bold text-primary underline-offset-2 hover:underline"
            >
              원본 작업 #{run.restart_of_run_id}
            </Link>
          ) : null}
        </div>
        <div className="w-full shrink-0 lg:w-72">
          <div className="mb-1 flex items-center justify-between text-[12px]">
            <span className="font-medium text-text-secondary">진행률</span>
            <span className="font-bold tabular-nums">{progress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-muted">
            <div
              className={runOutcomeProgressBarClass(run)}
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
  error,
  onRetry,
  onOpenPlace,
}: {
  places: RunPlace[];
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  onOpenPlace: (place: RunPlace) => void;
}) {
  if (isLoading) return <EmptyState>불러오는 중...</EmptyState>;
  if (error) {
    return (
      <DataLoadError
        error={error}
        fallback="추출된 POI를 불러오지 못했습니다."
        onRetry={onRetry}
      />
    );
  }
  if (places.length === 0) return <EmptyState>추출된 POI가 없습니다.</EmptyState>;

  return (
    <div className="max-h-72 overflow-auto rounded-panel border border-border">
      <table className="w-full min-w-[34rem] text-sm">
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
              className="border-t border-border"
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
  error,
  onRetry,
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
  error: unknown;
  onRetry: () => void;
}) {
  if (isLoading) return <EmptyState>불러오는 중...</EmptyState>;
  if (error) {
    return (
      <DataLoadError
        error={error}
        fallback="수집된 영상을 불러오지 못했습니다."
        onRetry={onRetry}
      />
    );
  }
  if (videos.length === 0) return <EmptyState>수집된 영상이 없습니다.</EmptyState>;

  return (
    <div className="max-h-80 overflow-auto rounded-panel border border-border">
      <table className="w-full min-w-[42rem] text-sm">
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
            <tr key={video.video_id} className="border-t border-border">
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

// 라벨:값을 한 줄로 붙여 표시한다(예전엔 라벨/값이 각자 줄을 차지하는 2줄짜리
// 카드였다 — 재시도/등록/시작/종료처럼 짧은 값에는 불필요하게 넓은 면적이었다).
// `wrap`(대상/최근 오류처럼 길이가 정해지지 않은 값)은 한 줄로 자르지 않고
// 줄바꿈한다 — hover 전용 title 툴팁은 터치 기기에서 확인할 방법이 없다.
// `singleColumn`(페이지의 "작업" 세부 정보처럼 좁은 xl: 사이드바 칼럼에 들어갈 때):
// `sm:grid-cols-2`는 뷰포트 폭 기준이라 실제 렌더 폭이 좁아도 2열을 강제해
// 등록/시작/종료 같은 날짜 값이 눌릴 수 있다 — 이럴 땐 1열로 고정한다.
function MetricGrid({
  fields,
  singleColumn,
}: {
  fields: { label: string; value: string; wrap?: boolean }[];
  singleColumn?: boolean;
}) {
  return (
    <div
      className={`grid grid-cols-1 gap-x-4 ${singleColumn ? "" : "sm:grid-cols-2"}`}
    >
      {fields.map((field) => (
        <div
          key={field.label}
          className={`flex min-w-0 gap-3 border-b border-border py-1.5 last:border-b-0 ${
            singleColumn ? "" : "sm:[&:nth-last-child(-n+2)]:border-b-0"
          } ${field.wrap ? "items-start" : "items-baseline justify-between"}`}
        >
          <span className="shrink-0 text-[12px] text-text-secondary">
            {field.label}
          </span>
          <span
            className={
              field.wrap
                ? "min-w-0 flex-1 text-right text-[13px] font-bold break-words whitespace-normal"
                : "truncate text-[13px] font-bold"
            }
            title={field.wrap ? undefined : field.value}
          >
            {field.value}
          </span>
        </div>
      ))}
    </div>
  );
}

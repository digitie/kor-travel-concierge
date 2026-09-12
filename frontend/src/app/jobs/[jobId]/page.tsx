"use client";

import { Fragment, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeftIcon,
  CheckCircle2Icon,
  ExternalLinkIcon,
  ListVideoIcon,
  RefreshCwIcon,
} from "lucide-react";

import {
  getRun,
  getRunVideoStats,
  getVideoTranscript,
  reprocessVideos,
  RUN_QUEUE_QUERY_KEY,
  type RunVideoStat,
} from "@/lib/api";
import { AppShell } from "@/components/AppShell";
import { ConfirmActionButton } from "@/components/ConfirmActionButton";
import { DataLoadError, JobDetailView } from "@/components/JobDetailView";
import { JobLogView } from "@/components/JobLogDialog";
import { RunActionButtons } from "@/components/RunActionButtons";
import { EmptyState, MetricCard, Panel, Section } from "@/components/panels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { categoryDisplayLabel } from "@/lib/display-labels";

export default function JobDetailPage() {
  const params = useParams<{ jobId: string }>();
  const jobId = String(params.jobId);
  const router = useRouter();

  const runQuery = useQuery({
    queryKey: ["run", jobId],
    queryFn: () => getRun(jobId),
    refetchInterval: 8_000,
  });
  const statsQuery = useQuery({
    queryKey: ["run-video-stats", jobId],
    queryFn: () => getRunVideoStats(jobId),
    enabled: !runQuery.isError,
    refetchInterval: 15_000,
  });
  const run = runQuery.data;
  const stats = statsQuery.data ?? [];

  return (
    <AppShell
      title="작업 상세"
      description={`작업 ID ${jobId}`}
      actions={
        <>
          {run ? (
            <RunActionButtons
              run={run}
              size="sm"
              restartBehavior="navigate"
              onDeleted={(deletedJobId) =>
                router.push(`/jobs?deleted=${encodeURIComponent(deletedJobId)}`)
              }
            />
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              void runQuery.refetch();
              void statsQuery.refetch();
            }}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => router.back()}
          >
            <ArrowLeftIcon data-icon="inline-start" />
            뒤로
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-5">
        {runQuery.isLoading ? (
          <Panel title="작업">
            <EmptyState>불러오는 중...</EmptyState>
          </Panel>
        ) : runQuery.error ? (
          <Panel title="작업">
            <DataLoadError
              error={runQuery.error}
              fallback="작업 정보를 불러오지 못했습니다."
              onRetry={() => void runQuery.refetch()}
            />
          </Panel>
        ) : run ? (
          // 중요도 순 배치: 세부 정보 다음에 영상 처리(afterDetails)를 끼워 위로
          // 올리고, 로그는 hideLog로 여기서 숨긴 뒤 화면 맨 아래에 따로 둔다.
          <JobDetailView
            run={run}
            hideVideos
            hideLog
            variant="page"
            afterDetails={
              <VideoStatsSection
                stats={stats}
                isLoading={statsQuery.isLoading}
                error={statsQuery.error}
                onRetry={() => void statsQuery.refetch()}
                defaultCategory={categoryDisplayLabel(
                  run.default_category_label ?? run.default_category_code,
                )}
              />
            }
          />
        ) : (
          <Panel title="작업">
            <EmptyState>작업을 찾을 수 없습니다.</EmptyState>
          </Panel>
        )}

        {!runQuery.error && run ? (
          <Section title="로그">
            <Panel title="상태 로그·오류">
              <JobLogView status={run} />
            </Panel>
          </Section>
        ) : null}
      </div>
    </AppShell>
  );
}

function VideoStatsSection({
  stats,
  isLoading,
  error,
  onRetry,
  defaultCategory,
}: {
  stats: RunVideoStat[];
  isLoading: boolean;
  error: unknown;
  onRetry: () => void;
  defaultCategory: string;
}) {
  const hasError = Boolean(error);
  const processed = stats.filter((stat) => stat.poi_total > 0).length;
  const totalPoi = stats.reduce((sum, stat) => sum + stat.poi_total, 0);
  const reviewPoi = stats.reduce((sum, stat) => sum + stat.poi_needs_review, 0);

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-[15px] font-bold">영상 처리</h2>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={<ListVideoIcon className="size-4" />}
          label="처리 영상"
          value={
            hasError
              ? "—"
              : `${processed.toLocaleString()} / ${stats.length.toLocaleString()}개`
          }
        />
        <MetricCard
          icon={<CheckCircle2Icon className="size-4" />}
          label="추출 POI"
          value={hasError ? "—" : `${totalPoi.toLocaleString()}개`}
        />
        <MetricCard
          icon={<CheckCircle2Icon className="size-4" />}
          label="검수 대기"
          value={hasError ? "—" : `${reviewPoi.toLocaleString()}개`}
          tone={reviewPoi > 0 ? "warn" : "neutral"}
        />
        <MetricCard
          icon={<CheckCircle2Icon className="size-4" />}
          label="기본 카테고리"
          value={defaultCategory}
        />
      </section>

      <Panel title="영상별 POI · 보정 자막 · 재실행">
        {isLoading ? (
          <EmptyState>불러오는 중...</EmptyState>
        ) : error ? (
          <DataLoadError
            error={error}
            fallback="영상 처리 통계를 불러오지 못했습니다."
            onRetry={onRetry}
          />
        ) : stats.length === 0 ? (
          <EmptyState>수집된 영상이 없습니다.</EmptyState>
        ) : (
          <div className="max-h-[34rem] overflow-auto rounded-panel border border-border">
            <table className="w-full min-w-[60rem] text-sm">
              <thead className="sticky top-0 z-10 bg-surface-subtle text-left text-xs font-semibold text-text-secondary">
                <tr>
                  <th className="px-3 py-2">영상</th>
                  <th className="px-3 py-2">POI</th>
                  <th className="px-3 py-2">상태</th>
                  <th className="px-3 py-2 text-right">액션</th>
                </tr>
              </thead>
              <tbody>
                {stats.map((stat) => (
                  <VideoStatRows key={stat.video_id} stat={stat} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </section>
  );
}

function VideoStatRows({ stat }: { stat: RunVideoStat }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [showTranscript, setShowTranscript] = useState(false);
  const transcriptQuery = useQuery({
    queryKey: ["video-transcript", stat.video_id],
    queryFn: () => getVideoTranscript(stat.video_id),
    enabled: showTranscript,
  });
  const reprocess = useMutation({
    mutationFn: () => reprocessVideos([stat.video_id], "transcript"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: RUN_QUEUE_QUERY_KEY });
    },
  });

  return (
    <Fragment>
      <tr className="border-t border-border">
        <td className="px-3 py-2 align-top">
          <a
            href={stat.url}
            target="_blank"
            rel="noreferrer"
            className="flex min-w-0 items-start gap-1 font-medium"
          >
            <span className="line-clamp-2">{stat.title}</span>
            <ExternalLinkIcon className="mt-0.5 size-3 shrink-0 text-muted-foreground" />
          </a>
          <span className="font-mono text-[11px] text-text-secondary">
            {stat.video_id}
          </span>
        </td>
        <td className="px-3 py-2 align-top">
          <Badge variant="secondary">POI {stat.poi_total}</Badge>
        </td>
        <td className="px-3 py-2 align-top">
          <div className="flex flex-col gap-1 text-[12px] text-text-secondary">
            <span>자동 {stat.poi_auto.toLocaleString()}</span>
            <span>검수 대기 {stat.poi_needs_review.toLocaleString()}</span>
            <span>완료 {stat.poi_resolved.toLocaleString()}</span>
            {reprocess.isSuccess ? (
              <span className="text-primary">재처리 작업 등록됨</span>
            ) : reprocess.error ? (
              <span className="text-destructive">{reprocess.error.message}</span>
            ) : null}
          </div>
        </td>
        <td className="px-3 py-2 align-top">
          <div className="flex justify-end gap-1">
            <Button
              type="button"
              size="xs"
              variant="outline"
              onClick={() =>
                router.push(`/?video=${encodeURIComponent(stat.video_id)}`)
              }
            >
              결과
            </Button>
            <Button
              type="button"
              size="xs"
              variant="outline"
              onClick={() => setShowTranscript((value) => !value)}
            >
              {showTranscript ? "자막 닫기" : "자막"}
            </Button>
            <ConfirmActionButton
              title="이 영상을 다시 처리할까요?"
              description="자막 교정 → POI 추출을 처음부터 다시 실행합니다."
              confirmLabel="재실행"
              confirmVariant="default"
              onConfirm={() => reprocess.mutate()}
              trigger={
                <Button
                  type="button"
                  size="xs"
                  variant="outline"
                  disabled={reprocess.isPending}
                >
                  재실행
                </Button>
              }
            />
          </div>
        </td>
      </tr>
      {showTranscript ? (
        <tr className="border-t border-border bg-surface-row">
          <td colSpan={4} className="px-3 py-3">
            {transcriptQuery.isLoading ? (
              <EmptyState>불러오는 중...</EmptyState>
            ) : transcriptQuery.data?.text ? (
              <pre className="max-h-72 overflow-y-auto rounded-control border border-border bg-surface-subtle p-3 text-xs whitespace-pre-wrap">
                {transcriptQuery.data.text}
              </pre>
            ) : (
              <EmptyState>
                보정 자막이 없습니다(RustFS 미구성이거나 아직 저장 전).
              </EmptyState>
            )}
          </td>
        </tr>
      ) : null}
    </Fragment>
  );
}

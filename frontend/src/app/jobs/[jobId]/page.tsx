"use client";

import { VirtualTable } from "@kor-travel/ui/virtual-table";
import { createStore } from "zustand/vanilla";
import { useStore } from "zustand";

import { useState } from "react";
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
  const [viewStore] = useState(() =>
    createStore<{ expanded: Record<string, boolean> }>(() => ({
      expanded: {},
    })),
  );
  const expanded = useStore(viewStore, (state) => state.expanded);
  const toggleTranscript = (id: string) =>
    viewStore.setState((state) => ({
      expanded: { ...state.expanded, [id]: !state.expanded[id] },
    }));
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
            <VirtualTable
              data={stats}
              columns={[
                {
                  id: "video-0",
                  header: "영상",
                  enableSorting: false,
                  cell: ({ row: { original: stat } }) => (
                    <>
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
                    </>
                  ),
                },
                {
                  id: "video-1",
                  header: "POI",
                  enableSorting: false,
                  cell: ({ row: { original: stat } }) => (
                    <>
                      <Badge variant="secondary">POI {stat.poi_total}</Badge>
                    </>
                  ),
                },
                {
                  id: "video-2",
                  header: "상태",
                  enableSorting: false,
                  cell: ({ row: { original: stat } }) => (
                    <>
                      <div className="flex flex-col gap-1 text-[12px] text-text-secondary">
                        <span>자동 {stat.poi_auto.toLocaleString()}</span>
                        <span>
                          검수 대기 {stat.poi_needs_review.toLocaleString()}
                        </span>
                        <span>완료 {stat.poi_resolved.toLocaleString()}</span>
                      </div>
                    </>
                  ),
                },
                {
                  id: "video-3",
                  header: "액션",
                  enableSorting: false,
                  cell: ({ row: { original: stat } }) => (
                    <VideoStatActions
                      stat={stat}
                      expanded={Boolean(expanded[stat.video_id])}
                      onToggle={() => toggleTranscript(stat.video_id)}
                    />
                  ),
                },
              ]}
              getRowId={(stat) => stat.video_id}
              stickyHeader
              renderRowDetails={(stat) =>
                expanded[stat.video_id] ? (
                  <VideoStatTranscript stat={stat} />
                ) : null
              }
            />
          </div>
        )}
      </Panel>
    </section>
  );
}

function VideoStatActions({
  stat,
  expanded,
  onToggle,
}: {
  stat: RunVideoStat;
  expanded: boolean;
  onToggle: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const reprocess = useMutation({
    mutationFn: () => reprocessVideos([stat.video_id], "transcript"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: RUN_QUEUE_QUERY_KEY });
    },
  });
  return (
    <>
      <div className="flex flex-col gap-1">
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
            onClick={() => onToggle()}
          >
            {expanded ? "자막 닫기" : "자막"}
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
        {reprocess.isSuccess ? (
          <span className="text-primary">재처리 작업 등록됨</span>
        ) : reprocess.error ? (
          <span className="text-destructive">{reprocess.error.message}</span>
        ) : null}
      </div>
    </>
  );
}
function VideoStatTranscript({ stat }: { stat: RunVideoStat }) {
  const transcriptQuery = useQuery({
    queryKey: ["video-transcript", stat.video_id],
    queryFn: () => getVideoTranscript(stat.video_id),
  });
  return (
    <>
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
    </>
  );
}

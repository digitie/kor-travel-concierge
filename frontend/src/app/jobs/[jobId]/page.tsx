"use client";

import { Fragment, useState, type ReactNode } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
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
  type RunVideoStat,
} from "@/lib/api";
import { AppShell } from "@/components/AppShell";
import { JobDetailView } from "@/components/JobDetailView";
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
    refetchInterval: 15_000,
  });
  const run = runQuery.data;
  const stats = statsQuery.data ?? [];

  return (
    <AppShell
      title="작업 상세"
      description={`작업 ID ${jobId}`}
      section="상태"
      actions={
        <>
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
        ) : run ? (
          <JobDetailView run={run} hideVideos variant="page" />
        ) : (
          <Panel title="작업">
            <EmptyState>작업을 찾을 수 없습니다.</EmptyState>
          </Panel>
        )}

        <VideoStatsSection
          stats={stats}
          isLoading={statsQuery.isLoading}
          defaultCategory={
            run
              ? categoryDisplayLabel(
                  run.default_category_label ?? run.default_category_code,
                )
              : "-"
          }
        />
      </div>
    </AppShell>
  );
}

function VideoStatsSection({
  stats,
  isLoading,
  defaultCategory,
}: {
  stats: RunVideoStat[];
  isLoading: boolean;
  defaultCategory: string;
}) {
  const processed = stats.filter((stat) => stat.poi_total > 0).length;
  const totalPoi = stats.reduce((sum, stat) => sum + stat.poi_total, 0);
  const reviewPoi = stats.reduce((sum, stat) => sum + stat.poi_needs_review, 0);

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h2 className="text-[15px] font-bold">영상 처리</h2>
        <p className="text-[13px] text-text-secondary">
          영상별 POI 추출 결과, 보정 자막, 재실행 액션을 확인합니다.
        </p>
      </div>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={<ListVideoIcon className="size-4" />}
          label="처리 영상"
          value={`${processed.toLocaleString()} / ${stats.length.toLocaleString()}개`}
        />
        <MetricCard
          icon={<CheckCircle2Icon className="size-4" />}
          label="추출 POI"
          value={`${totalPoi.toLocaleString()}개`}
        />
        <MetricCard
          icon={<CheckCircle2Icon className="size-4" />}
          label="검수 대기"
          value={`${reviewPoi.toLocaleString()}개`}
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
        ) : stats.length === 0 ? (
          <EmptyState>수집된 영상이 없습니다.</EmptyState>
        ) : (
          <div className="max-h-[34rem] overflow-auto rounded-lg border border-surface-muted">
            <table className="w-full min-w-[60rem] text-[13px]">
              <thead className="sticky top-0 z-10 bg-surface-subtle text-left text-[12px] font-bold text-text-secondary">
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
  const [showTranscript, setShowTranscript] = useState(false);
  const transcriptQuery = useQuery({
    queryKey: ["video-transcript", stat.video_id],
    queryFn: () => getVideoTranscript(stat.video_id),
    enabled: showTranscript,
  });
  const reprocess = useMutation({
    mutationFn: () => reprocessVideos([stat.video_id], "transcript"),
  });

  return (
    <Fragment>
      <tr className="border-t border-surface-muted">
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
            <Button
              type="button"
              size="xs"
              variant="outline"
              disabled={reprocess.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    "이 영상의 자막 교정 → POI 추출을 다시 실행할까요?",
                  )
                ) {
                  reprocess.mutate();
                }
              }}
            >
              재실행
            </Button>
          </div>
        </td>
      </tr>
      {showTranscript ? (
        <tr className="border-t border-surface-muted bg-surface-row">
          <td colSpan={4} className="px-3 py-3">
            {transcriptQuery.isLoading ? (
              <EmptyState>불러오는 중...</EmptyState>
            ) : transcriptQuery.data?.text ? (
              <pre className="max-h-72 overflow-y-auto rounded-lg border border-surface-muted bg-surface-subtle p-3 text-xs whitespace-pre-wrap">
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

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]">
      <h2 className="mb-3 flex items-center gap-1.5 text-[14px] font-bold">
        <CheckCircle2Icon className="size-4 text-brand" />
        {title}
      </h2>
      {children}
    </section>
  );
}

function MetricCard({
  icon,
  label,
  value,
  tone = "neutral",
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone?: "neutral" | "active" | "warn";
}) {
  return (
    <div className="flex min-w-0 items-start gap-3 rounded-lg border border-surface-muted bg-card p-4 shadow-[var(--shadow-card)]">
      <span
        className={
          tone === "active"
            ? "mt-0.5 text-brand"
            : tone === "warn"
              ? "mt-0.5 text-warning"
              : "mt-0.5 text-text-secondary"
        }
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block text-[12px] font-bold uppercase tracking-[0.05em] text-text-secondary">
          {label}
        </span>
        <span className="mt-1 block text-[16px] font-bold leading-snug text-text-primary">
          {value}
        </span>
      </span>
    </div>
  );
}

function EmptyState({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-surface-muted bg-surface-subtle p-3 text-[13px] text-text-secondary">
      {children}
    </p>
  );
}

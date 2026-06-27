"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeftIcon, ExternalLinkIcon } from "lucide-react";

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
  const processed = stats.filter((s) => s.poi_total > 0).length;

  return (
    <AppShell
      title={`작업 상세 #${jobId}`}
      description="작업 진행, 결과, 영상별 처리 현황을 확인합니다."
      section="상태"
      actions={
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => router.back()}
        >
          <ArrowLeftIcon data-icon="inline-start" />
          뒤로
        </Button>
      }
    >
      <div className="flex flex-col gap-4 overflow-y-auto p-5">
        {runQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">불러오는 중…</p>
        ) : run ? (
          <JobDetailView run={run} hideVideos />
        ) : (
          <p className="text-sm text-muted-foreground">작업을 찾을 수 없습니다.</p>
        )}

        <div className="flex flex-col gap-2 border-t pt-4">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium">영상별 POI · 보정 자막 · 재실행</p>
            <span className="text-xs text-muted-foreground">
              {/* 진행 근사: POI가 추출된 영상 수 / 전체 영상 수. 정밀 단계 카운트는
                  백엔드 미추적이라 진행률·현재 메시지(위)로 보완. */}
              영상 {stats.length}개 중 {processed}개 처리
            </span>
          </div>
          {statsQuery.isLoading ? (
            <p className="text-xs text-muted-foreground">불러오는 중…</p>
          ) : stats.length === 0 ? (
            <p className="rounded-lg border p-2 text-xs text-muted-foreground">
              수집된 영상이 없습니다.
            </p>
          ) : (
            <div className="flex flex-col gap-2">
              {stats.map((stat) => (
                <VideoStatRow key={stat.video_id} stat={stat} />
              ))}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}

function VideoStatRow({ stat }: { stat: RunVideoStat }) {
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
    <div className="flex flex-col gap-2 rounded-lg border p-2.5">
      <div className="flex items-center justify-between gap-2">
        <a
          href={stat.url}
          target="_blank"
          rel="noreferrer"
          className="flex min-w-0 items-center gap-1 truncate text-sm font-medium hover:underline"
        >
          <span className="truncate">{stat.title}</span>
          <ExternalLinkIcon className="size-3 shrink-0 text-muted-foreground" />
        </a>
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

      <button
        type="button"
        onClick={() => router.push(`/?video=${encodeURIComponent(stat.video_id)}`)}
        title="이 영상의 POI를 결과 화면에서 필터로 보기"
        className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md text-left text-xs transition-colors hover:opacity-80"
      >
        <Badge variant="secondary">POI {stat.poi_total}</Badge>
        <span className="text-muted-foreground">
          자동 {stat.poi_auto} · 검수 대기 {stat.poi_needs_review} · 완료{" "}
          {stat.poi_resolved}
        </span>
        <span className="text-primary">결과에서 보기 →</span>
      </button>

      {reprocess.isSuccess ? (
        <p className="text-xs text-primary">재처리 작업으로 등록했습니다.</p>
      ) : reprocess.error ? (
        <p className="text-xs text-destructive">{reprocess.error.message}</p>
      ) : null}

      <button
        type="button"
        onClick={() => setShowTranscript((v) => !v)}
        className="w-fit text-xs text-muted-foreground hover:text-foreground"
      >
        {showTranscript ? "보정 자막 닫기 ▲" : "보정 자막 보기 ▼"}
      </button>
      {showTranscript ? (
        transcriptQuery.isLoading ? (
          <p className="text-xs text-muted-foreground">불러오는 중…</p>
        ) : transcriptQuery.data?.text ? (
          <pre className="max-h-60 overflow-y-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap">
            {transcriptQuery.data.text}
          </pre>
        ) : (
          <p className="rounded-md border p-2 text-xs text-muted-foreground">
            보정 자막이 없습니다(RustFS 미구성이거나 아직 저장 전).
          </p>
        )
      ) : null}
    </div>
  );
}

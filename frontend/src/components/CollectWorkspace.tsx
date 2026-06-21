"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ListChecksIcon,
  PencilIcon,
  RotateCcwIcon,
  SquareIcon,
  Trash2Icon,
  ZapIcon,
} from "lucide-react";

import {
  deleteSourceTarget,
  listRunQueue,
  listRuns,
  listSourceTargets,
  restartRun,
  runSourceTargetNow,
  stopRun,
  USER_JOB_TYPES,
  type CrawlRunSummary,
  type SourceTargetSummary,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { HarvestConsole } from "@/components/HarvestConsole";
import { JobDetailDialog } from "@/components/JobDetailDialog";
import { RecurringEditDialog } from "@/components/RecurringEditDialog";

export function CollectWorkspace() {
  const queryClient = useQueryClient();
  const [detailRun, setDetailRun] = useState<CrawlRunSummary | null>(null);
  const [detailTarget, setDetailTarget] = useState<SourceTargetSummary | null>(
    null,
  );
  const [editTarget, setEditTarget] = useState<SourceTargetSummary | null>(null);

  const runsQuery = useQuery({
    queryKey: ["runs", "user"],
    queryFn: () => listRuns({ limit: 40, jobTypes: USER_JOB_TYPES }),
    refetchInterval: 5_000,
  });
  const runQueueQuery = useQuery({
    queryKey: ["run-queue", "user"],
    queryFn: () => listRunQueue(USER_JOB_TYPES),
    refetchInterval: 2_000,
  });
  const sourceTargetsQuery = useQuery({
    queryKey: ["source-targets"],
    queryFn: listSourceTargets,
    refetchInterval: 15_000,
  });

  const invalidateJobs = () => {
    queryClient.invalidateQueries({ queryKey: ["runs"] });
    queryClient.invalidateQueries({ queryKey: ["run-queue"] });
  };
  const stopRunMutation = useMutation({ mutationFn: stopRun, onSuccess: invalidateJobs });
  const restartRunMutation = useMutation({ mutationFn: restartRun, onSuccess: invalidateJobs });
  const deleteTargetMutation = useMutation({
    mutationFn: deleteSourceTarget,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["source-targets"] }),
  });
  const runNowMutation = useMutation({
    mutationFn: runSourceTargetNow,
    onSuccess: () => {
      invalidateJobs();
      queryClient.invalidateQueries({ queryKey: ["source-targets"] });
    },
  });

  const isMutating = stopRunMutation.isPending || restartRunMutation.isPending;

  return (
    <div className="flex min-h-[calc(100vh-3rem)] flex-col lg:flex-row">
      <div className="shrink-0 border-b lg:w-[26rem] lg:border-b-0 lg:border-r">
        <HarvestConsole />
      </div>
      <div className="grid flex-1 grid-cols-1 md:grid-cols-2">
        <RunQueuePanel
          queueRuns={runQueueQuery.data ?? []}
          errorMessage={runQueueQuery.error?.message ?? null}
          onStop={(jobId) => stopRunMutation.mutate(jobId)}
          onRestart={(jobId) => restartRunMutation.mutate(jobId)}
          onDetail={setDetailRun}
          isMutating={isMutating}
        />
        <JobsPanel
          runs={runsQuery.data ?? []}
          targets={sourceTargetsQuery.data ?? []}
          errorMessage={
            runsQuery.error?.message ?? sourceTargetsQuery.error?.message ?? null
          }
          onStop={(jobId) => stopRunMutation.mutate(jobId)}
          onRestart={(jobId) => restartRunMutation.mutate(jobId)}
          onRunNow={(id) => runNowMutation.mutate(id)}
          onDetailRun={setDetailRun}
          onDetailTarget={setDetailTarget}
          onEditTarget={setEditTarget}
          onDeleteTarget={(id) => deleteTargetMutation.mutate(id)}
          isMutating={isMutating}
          isDeleting={deleteTargetMutation.isPending}
          isRunningNow={runNowMutation.isPending}
        />
      </div>

      <JobDetailDialog
        run={detailRun}
        target={detailTarget}
        onClose={() => {
          setDetailRun(null);
          setDetailTarget(null);
        }}
      />
      <RecurringEditDialog
        target={editTarget}
        onClose={() => setEditTarget(null)}
      />
    </div>
  );
}

// ─── labels ───────────────────────────────────────────────────────────────

function targetTypeLabel(type: string | null | undefined): string {
  if (type === "channel") return "유튜버";
  if (type === "playlist") return "재생목록";
  if (type === "keyword") return "검색어";
  if (type === "video") return "영상";
  return type ?? "대상";
}

function jobTypeLabel(type: string | null | undefined): string {
  const map: Record<string, string> = {
    harvest: "수집",
    source_scan: "예약 스캔",
    video_analysis: "영상 분석",
    deep_research: "심층 조사",
    transcript: "자막",
    geocode: "지오코딩",
    postprocess: "후처리",
  };
  return (type && map[type]) ?? type ?? "작업";
}

function runTargetType(run: CrawlRunSummary): string {
  return run.target_type_label ?? targetTypeLabel(run.target_type);
}
function runTargetValue(run: CrawlRunSummary): string {
  return run.target_label ?? run.target_id ?? "-";
}

function intervalLabel(minutes: number | null) {
  if (!minutes) return "-";
  if (minutes % 43200 === 0) return `${minutes / 43200}달`;
  if (minutes % 10080 === 0) return `${minutes / 10080}주일`;
  if (minutes % 1440 === 0) return `${minutes / 1440}일`;
  if (minutes % 60 === 0) return `${minutes / 60}시간`;
  return `${minutes}분`;
}

function formatRunTime(value: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function latestRunLog(run: CrawlRunSummary) {
  return run.status_logs.at(-1)?.message ?? null;
}

function progressBarClass(state: string) {
  if (state === "failed") return "h-full rounded-full bg-destructive";
  if (state === "done") return "h-full rounded-full bg-success";
  return "h-full rounded-full bg-primary";
}

// ─── panels ───────────────────────────────────────────────────────────────

function RunQueuePanel({
  queueRuns,
  errorMessage,
  onStop,
  onRestart,
  onDetail,
  isMutating,
}: {
  queueRuns: CrawlRunSummary[];
  errorMessage: string | null;
  onStop: (jobId: string) => void;
  onRestart: (jobId: string) => void;
  onDetail: (run: CrawlRunSummary) => void;
  isMutating: boolean;
}) {
  return (
    <section
      aria-label="실행 큐"
      className="flex flex-col gap-3 border-b p-3 md:border-b-0 md:border-r"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <ListChecksIcon className="size-4 text-muted-foreground" />
          실행 큐
        </h2>
        <Badge variant="secondary">{queueRuns.length}</Badge>
      </div>
      {errorMessage ? (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage}
        </p>
      ) : null}
      {queueRuns.length > 0 ? (
        queueRuns.map((run) => (
          <RunControlCard
            key={run.job_id}
            run={run}
            onStop={onStop}
            onRestart={onRestart}
            onDetail={onDetail}
            isMutating={isMutating}
          />
        ))
      ) : (
        <p className="rounded-lg border p-2 text-xs text-muted-foreground">
          실행 중이거나 대기 중인 작업이 없습니다.
        </p>
      )}
    </section>
  );
}

function JobsPanel({
  runs,
  targets,
  errorMessage,
  onStop,
  onRestart,
  onRunNow,
  onDetailRun,
  onDetailTarget,
  onEditTarget,
  onDeleteTarget,
  isMutating,
  isDeleting,
  isRunningNow,
}: {
  runs: CrawlRunSummary[];
  targets: SourceTargetSummary[];
  errorMessage: string | null;
  onStop: (jobId: string) => void;
  onRestart: (jobId: string) => void;
  onRunNow: (id: number) => void;
  onDetailRun: (run: CrawlRunSummary) => void;
  onDetailTarget: (target: SourceTargetSummary) => void;
  onEditTarget: (target: SourceTargetSummary) => void;
  onDeleteTarget: (id: number) => void;
  isMutating: boolean;
  isDeleting: boolean;
  isRunningNow: boolean;
}) {
  return (
    <section aria-label="작업" className="flex flex-col gap-3 p-3">
      <Tabs defaultValue="recurring">
        <TabsList className="w-full">
          <TabsTrigger value="recurring">반복 {targets.length}</TabsTrigger>
          <TabsTrigger value="oneoff">1회성 {runs.length}</TabsTrigger>
        </TabsList>
        {errorMessage ? (
          <p role="alert" className="mt-2 text-xs text-destructive">
            {errorMessage}
          </p>
        ) : null}
        <TabsContent value="recurring" className="mt-3 flex flex-col gap-2">
          {targets.length > 0 ? (
            targets.map((target) => (
              <div
                key={target.id}
                className="flex flex-col gap-1.5 rounded-lg border p-2 text-xs"
              >
                <button
                  type="button"
                  className="flex items-start justify-between gap-2 text-left"
                  onClick={() => onDetailTarget(target)}
                >
                  <span className="flex min-w-0 flex-col">
                    <span className="text-[11px] text-muted-foreground">
                      {target.target_type_label ??
                        targetTypeLabel(target.target_type)}
                    </span>
                    <span className="truncate font-medium">
                      {target.target_label ??
                        target.display_name ??
                        target.source_value}
                    </span>
                  </span>
                  <Badge variant={target.is_active ? "outline" : "secondary"}>
                    {target.is_active ? "활성" : "중지"}
                  </Badge>
                </button>
                <p className="text-muted-foreground">
                  {intervalLabel(target.scan_interval_minutes)} ·{" "}
                  {target.max_runs === 0
                    ? `무한 (${target.run_count}회)`
                    : `${target.run_count}/${target.max_runs}회`}{" "}
                  · 다음 {formatRunTime(target.next_crawl_at)}
                </p>
                {target.last_scan_error ? (
                  <p className="break-words text-destructive">
                    {target.last_scan_error}
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="xs"
                    disabled={isRunningNow}
                    onClick={() => onRunNow(target.id)}
                  >
                    <ZapIcon data-icon="inline-start" />
                    지금 진행
                  </Button>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    onClick={() => onEditTarget(target)}
                  >
                    <PencilIcon data-icon="inline-start" />
                    수정
                  </Button>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    disabled={isDeleting}
                    onClick={() => onDeleteTarget(target.id)}
                    aria-label={`${target.display_name ?? target.source_value} 반복 삭제`}
                  >
                    <Trash2Icon data-icon="inline-start" />
                    삭제
                  </Button>
                </div>
              </div>
            ))
          ) : (
            <p className="rounded-lg border p-2 text-xs text-muted-foreground">
              반복 수집 중인 작업이 없습니다. 수집 시작 시 “반복 검색”을 켜면 등록됩니다.
            </p>
          )}
        </TabsContent>
        <TabsContent value="oneoff" className="mt-3 flex flex-col gap-2">
          {runs.length > 0 ? (
            runs.map((run) => (
              <RunControlCard
                key={run.job_id}
                run={run}
                onStop={onStop}
                onRestart={onRestart}
                onDetail={onDetailRun}
                isMutating={isMutating}
              />
            ))
          ) : (
            <p className="rounded-lg border p-2 text-xs text-muted-foreground">
              작업이 없습니다.
            </p>
          )}
        </TabsContent>
      </Tabs>
    </section>
  );
}

// 작업 카드: 1번째 줄=대상(검색어/유튜버/재생목록 + 값), 2번째 줄=작업유형 + 메시지.
function RunControlCard({
  run,
  onStop,
  onRestart,
  onDetail,
  isMutating,
}: {
  run: CrawlRunSummary;
  onStop: (jobId: string) => void;
  onRestart: (jobId: string) => void;
  onDetail: (run: CrawlRunSummary) => void;
  isMutating: boolean;
}) {
  const isActive = run.state === "pending" || run.state === "running";
  const isTerminal =
    run.state === "done" || run.state === "failed" || run.state === "cancelled";

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border p-2 text-xs">
      <button
        type="button"
        className="flex items-start justify-between gap-2 text-left"
        onClick={() => onDetail(run)}
      >
        <span className="flex min-w-0 flex-col">
          <span className="text-[11px] text-muted-foreground">
            {runTargetType(run)}
          </span>
          <span className="truncate font-medium">{runTargetValue(run)}</span>
        </span>
        <Badge variant={run.state === "failed" ? "destructive" : "outline"}>
          {run.state}
        </Badge>
      </button>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={progressBarClass(run.state)}
          style={{ width: `${Math.round(run.progress * 100)}%` }}
        />
      </div>
      <p className="line-clamp-1 text-muted-foreground">
        <span className="mr-1 rounded bg-muted px-1 py-0.5 text-[10px] font-medium text-foreground">
          {run.job_type_label ?? jobTypeLabel(run.job_type)}
        </span>
        {run.current_message ?? latestRunLog(run) ?? "상세 로그 대기 중"}
      </p>
      <div className="flex gap-2">
        {isActive ? (
          <Button
            type="button"
            size="xs"
            variant="outline"
            disabled={isMutating}
            onClick={() => onStop(run.job_id)}
          >
            <SquareIcon data-icon="inline-start" />
            중지
          </Button>
        ) : null}
        {isTerminal ? (
          <Button
            type="button"
            size="xs"
            variant="outline"
            disabled={isMutating}
            onClick={() => onRestart(run.job_id)}
          >
            <RotateCcwIcon data-icon="inline-start" />
            다시 시작
          </Button>
        ) : null}
        <Button
          type="button"
          size="xs"
          variant="ghost"
          onClick={() => onDetail(run)}
        >
          상세
        </Button>
      </div>
    </div>
  );
}

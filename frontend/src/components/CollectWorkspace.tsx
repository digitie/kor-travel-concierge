"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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
  triggerPoiBatch,
  USER_JOB_TYPES,
  type CrawlRunSummary,
  type SourceTargetSummary,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { HarvestConsole } from "@/components/HarvestConsole";
import { JobDetailDialog } from "@/components/JobDetailDialog";
import { RecurringEditDialog } from "@/components/RecurringEditDialog";

export function CollectWorkspace() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [detailRun, setDetailRun] = useState<CrawlRunSummary | null>(null);
  const [detailTarget, setDetailTarget] = useState<SourceTargetSummary | null>(
    null,
  );
  // 1회성 작업 상세는 다이얼로그 대신 별도 페이지(/jobs/[id])로 이동한다.
  const openRunDetail = (run: CrawlRunSummary) =>
    router.push(`/jobs/${run.job_id}`);
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
  const poiBatchMutation = useMutation({
    mutationFn: triggerPoiBatch,
    onSuccess: invalidateJobs,
  });
  const deleteTargetMutation = useMutation({
    mutationFn: deleteSourceTarget,
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["source-targets"] }),
  });
  const runNowMutation = useMutation({
    mutationFn: ({ id, force }: { id: number; force: boolean }) =>
      runSourceTargetNow(id, force),
    onSuccess: () => {
      invalidateJobs();
      queryClient.invalidateQueries({ queryKey: ["source-targets"] });
    },
  });

  const isMutating = stopRunMutation.isPending || restartRunMutation.isPending;

  return (
    <div className="flex h-full min-h-[40rem] flex-col lg:min-h-0 lg:flex-row lg:overflow-hidden">
      <div className="shrink-0 border-b lg:w-[38rem] lg:overflow-y-auto lg:border-b-0 lg:border-r">
        <HarvestConsole />
        <div className="flex flex-col gap-1.5 border-t p-3">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="w-full"
            disabled={poiBatchMutation.isPending}
            onClick={() => poiBatchMutation.mutate()}
          >
            <ListChecksIcon data-icon="inline-start" />
            미처리 영상 POI 추출(묶음)
          </Button>
          {poiBatchMutation.data ? (
            <p className="text-xs text-muted-foreground">
              영상 {poiBatchMutation.data.videos}개를 {poiBatchMutation.data.enqueued_jobs}개
              작업으로 등록했습니다.
            </p>
          ) : poiBatchMutation.error ? (
            <p className="text-xs text-destructive">
              {poiBatchMutation.error.message}
            </p>
          ) : null}
        </div>
      </div>
      <div className="grid flex-1 grid-cols-1 md:grid-cols-2 lg:min-h-0">
        <RunQueuePanel
          queueRuns={runQueueQuery.data ?? []}
          errorMessage={runQueueQuery.error?.message ?? null}
          onStop={(jobId) => stopRunMutation.mutate(jobId)}
          onRestart={(jobId) => restartRunMutation.mutate(jobId)}
          onDetail={openRunDetail}
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
          onRunNow={(id, force) => runNowMutation.mutate({ id, force })}
          onDetailRun={openRunDetail}
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
    poi_batch: "장소 추출(묶음)",
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

function formatDateTime(value: string | null | undefined) {
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

function latestRunLog(run: CrawlRunSummary) {
  return run.status_logs.at(-1)?.message ?? null;
}

function runProgressPercent(run: CrawlRunSummary) {
  return `${Math.round(run.progress * 100)}%`;
}

function runStateVariant(state: string): "outline" | "secondary" | "destructive" {
  if (state === "failed") return "destructive";
  if (state === "running" || state === "done") return "secondary";
  return "outline";
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
      className="flex flex-col gap-3 border-b p-3 md:border-b-0 md:border-r lg:min-h-0"
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
      <div className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
        {queueRuns.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>상태</TableHead>
                <TableHead>대상</TableHead>
                <TableHead>진행</TableHead>
                <TableHead>최근 메시지</TableHead>
                <TableHead>시간</TableHead>
                <TableHead className="text-right">액션</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {queueRuns.map((run) => (
                <TableRow key={run.job_id}>
                  <TableCell>
                    <Badge variant={runStateVariant(run.state)}>{run.state}</Badge>
                  </TableCell>
                  <TableCell>
                    <button
                      type="button"
                      className="flex max-w-[18rem] flex-col gap-1 whitespace-normal text-left"
                      onClick={() => onDetail(run)}
                    >
                      <span className="text-[11px] font-bold tracking-[0.05em] text-text-secondary uppercase">
                        {runTargetType(run)}
                      </span>
                      <span className="font-bold leading-snug">{runTargetValue(run)}</span>
                      <span className="w-fit rounded bg-surface-subtle px-1.5 py-0.5 text-[11px] text-text-secondary">
                        {run.job_type_label ?? jobTypeLabel(run.job_type)}
                      </span>
                      {run.default_category_label ? (
                        <span className="w-fit rounded bg-surface-subtle px-1.5 py-0.5 text-[11px] text-text-secondary">
                          기본 {run.default_category_label}
                        </span>
                      ) : null}
                    </button>
                  </TableCell>
                  <TableCell>
                    <div className="flex w-28 flex-col gap-1">
                      <div className="h-1.5 overflow-hidden rounded-full bg-surface-muted">
                        <div
                          className={progressBarClass(run.state)}
                          style={{ width: runProgressPercent(run) }}
                        />
                      </div>
                      <span className="text-[12px] text-text-secondary">
                        {runProgressPercent(run)}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <p className="line-clamp-2 max-w-[18rem] whitespace-normal text-[13px] text-text-secondary">
                      {run.current_message ?? latestRunLog(run) ?? "상세 로그 대기 중"}
                    </p>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-col text-[12px] text-text-secondary">
                      <span>등록 {formatDateTime(run.created_at)}</span>
                      <span>시작 {formatDateTime(run.started_at)}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <RunActionButtons
                      run={run}
                      onStop={onStop}
                      onRestart={onRestart}
                      onDetail={onDetail}
                      isMutating={isMutating}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="rounded-lg border p-2 text-xs text-muted-foreground">
            실행 중이거나 대기 중인 작업이 없습니다.
          </p>
        )}
      </div>
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
  onRunNow: (id: number, force: boolean) => void;
  onDetailRun: (run: CrawlRunSummary) => void;
  onDetailTarget: (target: SourceTargetSummary) => void;
  onEditTarget: (target: SourceTargetSummary) => void;
  onDeleteTarget: (id: number) => void;
  isMutating: boolean;
  isDeleting: boolean;
  isRunningNow: boolean;
}) {
  // #7: "지금 실행" 클릭 시 강제 다운로드 여부를 묻는 다이얼로그.
  const [runNowTarget, setRunNowTarget] = useState<SourceTargetSummary | null>(
    null,
  );
  const [runNowForce, setRunNowForce] = useState(false);
  return (
    <section aria-label="작업" className="flex flex-col gap-3 p-3 lg:min-h-0 lg:overflow-y-auto">
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
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>대상</TableHead>
                  <TableHead>주기</TableHead>
                  <TableHead>기본</TableHead>
                  <TableHead>누적</TableHead>
                  <TableHead>일정</TableHead>
                  <TableHead>상태</TableHead>
                  <TableHead className="text-right">액션</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {targets.map((target) => {
                  const targetName =
                    target.target_label ?? target.display_name ?? target.source_value;
                  return (
                    <TableRow key={target.id}>
                      <TableCell>
                        <button
                          type="button"
                          className="flex max-w-[18rem] flex-col gap-1 whitespace-normal text-left"
                          onClick={() => onDetailTarget(target)}
                        >
                          <span className="text-[11px] font-bold tracking-[0.05em] text-text-secondary uppercase">
                            {target.target_type_label ??
                              targetTypeLabel(target.target_type)}
                          </span>
                          <span className="font-bold leading-snug">{targetName}</span>
                          <span className="break-all font-mono text-[11px] text-text-secondary">
                            {target.source_value === targetName
                              ? `#${target.id}`
                              : target.source_value}
                          </span>
                        </button>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col text-[13px]">
                          <span>{intervalLabel(target.scan_interval_minutes)}</span>
                          <span className="text-[12px] text-text-secondary">
                            회당 {target.max_videos ?? "-"}개
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">
                          {target.default_category_label ?? "unknown"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col text-[13px]">
                          <span>
                            {target.max_runs === 0
                              ? `무한 (${target.run_count}회)`
                              : `${target.run_count}/${target.max_runs}회`}
                          </span>
                          <span className="text-[12px] text-text-secondary">
                            최근 {formatRunTime(target.last_crawled_at)}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col text-[12px] text-text-secondary">
                          <span>다음 {formatDateTime(target.next_crawl_at)}</span>
                          <span>스캔 {formatDateTime(target.last_scan_at)}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex max-w-[14rem] flex-col gap-1 whitespace-normal">
                          <Badge variant={target.is_active ? "outline" : "secondary"}>
                            {target.is_active ? "활성" : "중지"}
                          </Badge>
                          {target.last_scan_error ? (
                            <span className="line-clamp-2 text-[12px] text-destructive">
                              {target.last_scan_error}
                            </span>
                          ) : (
                            <span className="text-[12px] text-text-secondary">
                              실패 {target.scan_failure_count}회
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          <Button
                            type="button"
                            size="xs"
                            disabled={isRunningNow}
                            onClick={() => {
                              setRunNowForce(false);
                              setRunNowTarget(target);
                            }}
                          >
                            <ZapIcon data-icon="inline-start" />
                            실행
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
                            variant="destructive"
                            disabled={isDeleting}
                            onClick={() => onDeleteTarget(target.id)}
                            aria-label={`${targetName} 반복 삭제`}
                          >
                            <Trash2Icon data-icon="inline-start" />
                            삭제
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          ) : (
            <p className="rounded-lg border p-2 text-xs text-muted-foreground">
              반복 수집 중인 작업이 없습니다. 수집 시작 시 “반복 검색”을 켜면 등록됩니다.
            </p>
          )}
        </TabsContent>
        <TabsContent value="oneoff" className="mt-3 flex flex-col gap-2">
          {runs.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>상태</TableHead>
                  <TableHead>대상</TableHead>
                  <TableHead>진행</TableHead>
                  <TableHead>결과/메시지</TableHead>
                  <TableHead>시간</TableHead>
                  <TableHead className="text-right">액션</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((run) => (
                  <TableRow key={run.job_id}>
                    <TableCell>
                      <Badge variant={runStateVariant(run.state)}>{run.state}</Badge>
                    </TableCell>
                    <TableCell>
                      <button
                        type="button"
                        className="flex max-w-[18rem] flex-col gap-1 whitespace-normal text-left"
                        onClick={() => onDetailRun(run)}
                      >
                        <span className="text-[11px] font-bold tracking-[0.05em] text-text-secondary uppercase">
                          {runTargetType(run)}
                        </span>
                        <span className="font-bold leading-snug">{runTargetValue(run)}</span>
                        <span className="w-fit rounded bg-surface-subtle px-1.5 py-0.5 text-[11px] text-text-secondary">
                          {run.job_type_label ?? jobTypeLabel(run.job_type)}
                        </span>
                        {run.default_category_label ? (
                          <span className="w-fit rounded bg-surface-subtle px-1.5 py-0.5 text-[11px] text-text-secondary">
                            기본 {run.default_category_label}
                          </span>
                        ) : null}
                      </button>
                    </TableCell>
                    <TableCell>
                      <div className="flex w-28 flex-col gap-1">
                        <div className="h-1.5 overflow-hidden rounded-full bg-surface-muted">
                          <div
                            className={progressBarClass(run.state)}
                            style={{ width: runProgressPercent(run) }}
                          />
                        </div>
                        <span className="text-[12px] text-text-secondary">
                          {runProgressPercent(run)}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <p className="line-clamp-2 max-w-[18rem] whitespace-normal text-[13px] text-text-secondary">
                        {runHistoryLine(run) ??
                          run.current_message ??
                          latestRunLog(run) ??
                          "상세 로그 대기 중"}
                      </p>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col text-[12px] text-text-secondary">
                        <span>시작 {formatDateTime(run.started_at)}</span>
                        <span>종료 {formatDateTime(run.finished_at)}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <RunActionButtons
                        run={run}
                        onStop={onStop}
                        onRestart={onRestart}
                        onDetail={onDetailRun}
                        isMutating={isMutating}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="rounded-lg border p-2 text-xs text-muted-foreground">
              작업이 없습니다.
            </p>
          )}
        </TabsContent>
      </Tabs>
      <Dialog
        open={runNowTarget != null}
        onOpenChange={(next) => !next && setRunNowTarget(null)}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>지금 실행</DialogTitle>
            <DialogDescription>
              {runNowTarget?.display_name ?? runNowTarget?.source_value}
            </DialogDescription>
          </DialogHeader>
          <label className="flex items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              className="size-4 rounded border"
              checked={runNowForce}
              onChange={(event) => setRunNowForce(event.target.checked)}
            />
            강제 다운로드 (전체 재수집)
          </label>
          <p className="text-xs text-muted-foreground">
            체크하면 이미 본 영상 이후만 받는 증분 수집 대신 처음부터 다시 받습니다.
          </p>
          <DialogFooter>
            <DialogClose
              render={
                <Button type="button" variant="outline">
                  취소
                </Button>
              }
            />
            <Button
              type="button"
              disabled={isRunningNow}
              onClick={() => {
                if (runNowTarget) onRunNow(runNowTarget.id, runNowForce);
                setRunNowTarget(null);
              }}
            >
              실행
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

// 실행 기록 한 줄: 종료 시각 + 수집/신규 영상 수(결과에 있을 때만). 신규 POI 수 등
// 더 상세한 집계는 작업 상세 페이지(후속 작업)에서 제공한다.
function runHistoryLine(run: CrawlRunSummary): string | null {
  const r = (run.result ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  if (
    run.finished_at &&
    (run.state === "done" || run.state === "failed" || run.state === "cancelled")
  ) {
    parts.push(run.finished_at.slice(5, 16).replace("T", " "));
  }
  if (typeof r.discovered === "number") parts.push(`수집 ${r.discovered}`);
  if (typeof r.inserted === "number") parts.push(`신규 ${r.inserted}`);
  return parts.length ? parts.join(" · ") : null;
}

function RunActionButtons({
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
    <div className="flex justify-end gap-1">
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
  );
}

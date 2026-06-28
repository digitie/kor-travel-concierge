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
  listSourceTargets,
  restartRun,
  runSourceTargetNow,
  stopRun,
  triggerPoiBatch,
  USER_JOB_TYPES,
  type CrawlRunSummary,
  type SourceTargetSummary,
} from "@/lib/api";
import {
  categoryDisplayLabel,
  jobTypeDisplayLabel,
  runStateLabel,
  targetTypeDisplayLabel,
} from "@/lib/display-labels";
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
  const queueRuns = runQueueQuery.data ?? [];
  const activeRun =
    queueRuns.find((run) => run.state.toLowerCase() === "running") ??
    queueRuns.find((run) => run.state.toLowerCase() === "pending") ??
    null;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <div className="grid min-h-0 shrink-0 grid-cols-1 border-b lg:h-96 lg:grid-cols-[minmax(24rem,38rem)_1fr] lg:overflow-hidden">
        <div className="min-h-0 lg:overflow-y-auto lg:border-r">
          <HarvestConsole />
        </div>
        <div className="flex min-h-0 flex-col lg:overflow-y-auto">
          <ActiveRunPanel
            run={activeRun}
            errorMessage={runQueueQuery.error?.message ?? null}
            onStop={(jobId) => stopRunMutation.mutate(jobId)}
            onRestart={(jobId) => restartRunMutation.mutate(jobId)}
            onDetail={openRunDetail}
            isMutating={isMutating}
          />
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
                영상 {poiBatchMutation.data.videos}개를{" "}
                {poiBatchMutation.data.enqueued_jobs}개 작업으로 등록했습니다.
              </p>
            ) : poiBatchMutation.error ? (
              <p className="text-xs text-destructive">
                {poiBatchMutation.error.message}
              </p>
            ) : null}
          </div>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        <JobsPanel
          targets={sourceTargetsQuery.data ?? []}
          errorMessage={sourceTargetsQuery.error?.message ?? null}
          onRunNow={(id, force) => runNowMutation.mutate({ id, force })}
          onDetailTarget={setDetailTarget}
          onEditTarget={setEditTarget}
          onDeleteTarget={(id) => deleteTargetMutation.mutate(id)}
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
  return targetTypeDisplayLabel(type);
}

function jobTypeLabel(type: string | null | undefined): string {
  return jobTypeDisplayLabel(type);
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

// ─── panels ───────────────────────────────────────────────────────────────

function ActiveRunPanel({
  run,
  errorMessage,
  onStop,
  onRestart,
  onDetail,
  isMutating,
}: {
  run: CrawlRunSummary | null;
  errorMessage: string | null;
  onStop: (jobId: string) => void;
  onRestart: (jobId: string) => void;
  onDetail: (run: CrawlRunSummary) => void;
  isMutating: boolean;
}) {
  return (
    <section
      aria-label="진행 중 작업"
      className="flex flex-col gap-3 border-t p-3"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <ListChecksIcon className="size-4 text-muted-foreground" />
          진행 중 작업
        </h2>
        <Badge variant="secondary">{run ? "1" : "0"}</Badge>
      </div>
      {errorMessage ? (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage}
        </p>
      ) : null}
      {run ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>상태</TableHead>
              <TableHead>대상</TableHead>
              <TableHead>진행</TableHead>
              <TableHead>최근 메시지</TableHead>
              <TableHead className="text-right">액션</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>
                <Badge variant={runStateVariant(run.state)}>
                  {runStateLabel(run.state)}
                </Badge>
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
                </button>
              </TableCell>
              <TableCell>
                <div className="flex w-24 flex-col gap-1">
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
                <p className="line-clamp-2 max-w-[14rem] whitespace-normal text-[13px] text-text-secondary">
                  {run.current_message ?? latestRunLog(run) ?? "상세 로그 대기 중"}
                </p>
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
          </TableBody>
        </Table>
      ) : (
        <p className="rounded-lg border p-2 text-xs text-muted-foreground">
          실행 중이거나 대기 중인 작업이 없습니다.
        </p>
      )}
    </section>
  );
}

function JobsPanel({
  targets,
  errorMessage,
  onRunNow,
  onDetailTarget,
  onEditTarget,
  onDeleteTarget,
  isDeleting,
  isRunningNow,
}: {
  targets: SourceTargetSummary[];
  errorMessage: string | null;
  onRunNow: (id: number, force: boolean) => void;
  onDetailTarget: (target: SourceTargetSummary) => void;
  onEditTarget: (target: SourceTargetSummary) => void;
  onDeleteTarget: (id: number) => void;
  isDeleting: boolean;
  isRunningNow: boolean;
}) {
  // #7: "지금 실행" 클릭 시 강제 다운로드 여부를 묻는 다이얼로그.
  const [runNowTarget, setRunNowTarget] = useState<SourceTargetSummary | null>(
    null,
  );
  const [runNowForce, setRunNowForce] = useState(false);
  return (
    <section
      aria-label="반복 작업"
      className="flex h-full min-h-0 flex-col gap-3 pt-3"
    >
      <div className="flex items-center justify-between gap-3 px-3">
        <h2 className="text-sm font-semibold">반복 작업</h2>
        <Badge variant="secondary">{targets.length}</Badge>
      </div>
      {errorMessage ? (
        <p role="alert" className="px-3 text-xs text-destructive">
          {errorMessage}
        </p>
      ) : null}
      {targets.length > 0 ? (
        <div className="min-h-0 flex-1 overflow-y-auto">
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
                        {categoryDisplayLabel(
                          target.default_category_label ??
                            target.default_category_code,
                        )}
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
        </div>
      ) : (
        <p className="mx-3 rounded-lg border p-2 text-xs text-muted-foreground">
          반복 수집 중인 작업이 없습니다. 수집 시작 시 “반복 검색”을 켜면 등록됩니다.
        </p>
      )}
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
  const normalized = run.state.toLowerCase();
  const isActive = normalized === "pending" || normalized === "running";
  const isTerminal =
    normalized === "done" ||
    normalized === "failed" ||
    normalized === "cancelled" ||
    normalized === "canceled";

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
        variant="outline"
        onClick={() => onDetail(run)}
      >
        상세
      </Button>
    </div>
  );
}

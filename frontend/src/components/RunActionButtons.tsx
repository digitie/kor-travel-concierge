"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2Icon,
  RotateCcwIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react";

import {
  deleteRun,
  restartRun,
  RUN_QUEUE_QUERY_KEY,
  stopRun,
  type CrawlRunSummary,
  type DeleteRunResult,
  type RestartRunResult,
} from "@/lib/api";
import { isTerminalRun } from "@/lib/display-labels";
import { ConfirmActionButton } from "@/components/ConfirmActionButton";
import { Button } from "@/components/ui/button";

// 작업 목록/상세의 상세·중지·다시 시작·삭제 버튼이 함께 쓰는 최소 너비 — 라벨
// 길이가 제각각(2자~4자)이라 없으면 액션 칼럼에서 버튼 폭이 행마다 들쭉날쭉해
// 보인다. 여러 파일(CollectWorkspace/JobsDashboard)이 같은 값을 반복하지 않도록
// 여기서 export한다.
export const ACTION_BUTTON_WIDTH_CLASS = "min-w-[4.5rem] justify-center";

export type RunActionFeedback =
  | { kind: "stopped"; jobId: string }
  | { kind: "deleted"; jobId: string }
  | { kind: "restarted"; jobId: string; created: boolean }
  | {
      kind: "error";
      action: "stop" | "delete" | "restart";
      jobId: string;
      message: string;
    };

export function RunActionButtons({
  run,
  size = "xs",
  restartBehavior = "refresh",
  onFeedback,
  onDeleted,
}: {
  run: CrawlRunSummary;
  size?: "xs" | "sm";
  restartBehavior?: "navigate" | "refresh";
  onFeedback?: (feedback: RunActionFeedback) => void;
  onDeleted?: (jobId: string) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const state = run.state.toLowerCase();
  const actionTargetLabel =
    run.target_label ?? run.target_id ?? run.source ?? `작업 #${run.job_id}`;

  async function invalidateRunQueries(
    jobIds: string[],
    { includeDetail = true }: { includeDetail?: boolean } = {},
  ) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["runs"] }),
      queryClient.invalidateQueries({ queryKey: RUN_QUEUE_QUERY_KEY }),
      ...(includeDetail
        ? jobIds.flatMap((jobId) => [
            queryClient.invalidateQueries({ queryKey: ["run", jobId] }),
            queryClient.invalidateQueries({ queryKey: ["run-video-stats", jobId] }),
            queryClient.invalidateQueries({ queryKey: ["job-videos", jobId] }),
            queryClient.invalidateQueries({ queryKey: ["job-places", jobId] }),
          ])
        : []),
    ]);
  }

  const stopMutation = useMutation({
    mutationFn: () => stopRun(run.job_id),
    onSuccess: async () => {
      onFeedback?.({ kind: "stopped", jobId: run.job_id });
      await invalidateRunQueries([run.job_id]);
    },
    onError: (error) => {
      onFeedback?.({
        kind: "error",
        action: "stop",
        jobId: run.job_id,
        message: error.message,
      });
    },
  });
  const restartMutation = useMutation({
    mutationFn: () => restartRun(run.job_id),
    onSuccess: async (result: RestartRunResult) => {
      onFeedback?.({
        kind: "restarted",
        jobId: result.job_id,
        created: result.created,
      });
      if (restartBehavior === "navigate") {
        router.push(`/jobs/${result.job_id}`);
      }
      await invalidateRunQueries([run.job_id, result.job_id]);
    },
    onError: (error) => {
      onFeedback?.({
        kind: "error",
        action: "restart",
        jobId: run.job_id,
        message: error.message,
      });
    },
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteRun(run.job_id),
    onSuccess: async (result: DeleteRunResult) => {
      // 상세 화면은 삭제 직후 이력 페이지로 이동한다. 삭제된 run 상세 query를
      // 여기서 다시 fetch하면 이동 전 404가 의도치 않은 console 오류가 되므로
      // 목록/대기열만 갱신한다.
      await invalidateRunQueries([run.job_id], { includeDetail: false });
      onFeedback?.({ kind: "deleted", jobId: result.job_id });
      onDeleted?.(result.job_id);
    },
    onError: (error) => {
      onFeedback?.({
        kind: "error",
        action: "delete",
        jobId: run.job_id,
        message: error.message,
      });
    },
  });

  const isPending =
    stopMutation.isPending ||
    restartMutation.isPending ||
    deleteMutation.isPending;
  const error =
    deleteMutation.error ?? stopMutation.error ?? restartMutation.error;
  const restartResult = restartMutation.data;

  if (state !== "running" && !isTerminalRun(run.state)) {
    return null;
  }

  return (
    <div className="flex min-w-0 flex-col items-end gap-1">
      <div className="flex flex-wrap justify-end gap-1">
        {state === "running" ? (
          <ConfirmActionButton
            title="이 작업을 중지할까요?"
            description="현재 단계가 안전하게 끝난 뒤 작업이 취소됩니다. 이미 저장된 결과는 유지됩니다."
            confirmLabel="중지"
            onConfirm={() => stopMutation.mutate()}
            trigger={
              <Button
                type="button"
                size={size}
                variant="destructive"
                className={ACTION_BUTTON_WIDTH_CLASS}
                disabled={isPending}
              >
                {stopMutation.isPending ? (
                  <Loader2Icon data-icon="inline-start" className="animate-spin" />
                ) : (
                  <SquareIcon data-icon="inline-start" />
                )}
                {stopMutation.isPending ? "중지 요청 중" : "중지"}
              </Button>
            }
          />
        ) : null}
        {isTerminalRun(run.state) ? (
          <>
            <ConfirmActionButton
              title="이 작업을 다시 시작할까요?"
              description="같은 입력으로 새 작업을 등록합니다. 이미 진행 중인 재시작 작업이 있으면 중복 생성하지 않고 그 작업을 사용합니다."
              confirmLabel="다시 시작"
              confirmVariant="default"
              onConfirm={() => restartMutation.mutate()}
              trigger={
                <Button
                  type="button"
                  size={size}
                  variant="outline"
                  className={ACTION_BUTTON_WIDTH_CLASS}
                  disabled={isPending}
                >
                  {restartMutation.isPending ? (
                    <Loader2Icon data-icon="inline-start" className="animate-spin" />
                  ) : (
                    <RotateCcwIcon data-icon="inline-start" />
                  )}
                  {restartMutation.isPending ? "등록 중" : "다시 시작"}
                </Button>
              }
            />
            <ConfirmActionButton
              title={`"${actionTargetLabel}" 작업을 삭제할까요?`}
              description={`작업 #${run.job_id}의 종료 기록과 상태 로그를 삭제합니다. 수집된 영상·장소·원본 미디어는 삭제하지 않습니다. 연결된 재시작·후속 작업이 있으면 먼저 정리해야 합니다. 이 작업은 되돌릴 수 없습니다.`}
              confirmLabel="삭제"
              onConfirm={() => deleteMutation.mutate()}
              trigger={
                <Button
                  type="button"
                  size={size}
                  variant="destructive"
                  className={ACTION_BUTTON_WIDTH_CLASS}
                  disabled={isPending}
                >
                  {deleteMutation.isPending ? (
                    <Loader2Icon data-icon="inline-start" className="animate-spin" />
                  ) : (
                    <Trash2Icon data-icon="inline-start" />
                  )}
                  {deleteMutation.isPending ? "삭제 중" : "삭제"}
                </Button>
              }
            />
          </>
        ) : null}
      </div>
      {error && !onFeedback ? (
        <p role="alert" className="max-w-64 text-right text-[11px] text-destructive">
          {error.message}
        </p>
      ) : null}
      {restartBehavior === "refresh" && restartResult && !onFeedback ? (
        <p
          role="status"
          className="max-w-64 text-right text-[11px] text-text-secondary"
        >
          {restartResult.created
            ? "새 작업을 등록했습니다."
            : "이미 진행 중인 재시작 작업을 사용합니다."}{" "}
          <Link
            href={`/jobs/${restartResult.job_id}`}
            className="font-bold text-primary underline-offset-2 hover:underline"
          >
            작업 보기
          </Link>
        </p>
      ) : stopMutation.isSuccess && !onFeedback ? (
        <p
          role="status"
          className="max-w-64 text-right text-[11px] text-text-secondary"
        >
          중지를 요청했습니다.
        </p>
      ) : null}
    </div>
  );
}

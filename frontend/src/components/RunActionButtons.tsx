"use client";

import {
  Loader2Icon,
  RotateCcwIcon,
  SquareIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { useRunActions, type RunActionFeedback } from "./useRunActions";

import { ConfirmActionButton } from "@/components/ConfirmActionButton";
import { Button } from "@/components/ui/button";
import { type CrawlRunSummary, type RestartRunResult } from "@/lib/api";
import { isTerminalRun } from "@/lib/display-labels";

// 작업 목록/상세의 상세·중지·다시 시작·삭제 버튼이 함께 쓰는 최소 너비 — 라벨
// 길이가 제각각(2자~4자)이라 없으면 액션 칼럼에서 버튼 폭이 행마다 들쭉날쭉해
// 보인다. 여러 파일(CollectWorkspace/JobsDashboard)이 같은 값을 반복하지 않도록
// 여기서 export한다.
export const ACTION_BUTTON_WIDTH_CLASS = "min-w-[4.5rem] justify-center";

export type { RunActionFeedback } from "./useRunActions";

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
  const {
    stopMutation,
    restartMutation,
    deleteMutation,
    isPending,
    error,
    restartResult,
  } = useRunActions({ run, restartBehavior, onFeedback, onDeleted });
  const state = run.state.toLowerCase();
  const actionTargetLabel =
    run.target_label ?? run.target_id ?? run.source ?? `작업 #${run.job_id}`;

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
                  <Loader2Icon
                    data-icon="inline-start"
                    className="animate-spin"
                  />
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
            <RestartRunAction
              restartMutation={restartMutation}
              size={size}
              isPending={isPending}
            />
            <DeleteRunAction
              actionTargetLabel={actionTargetLabel}
              run={run}
              deleteMutation={deleteMutation}
              size={size}
              isPending={isPending}
            />
          </>
        ) : null}
      </div>
      <RunActionStatus
        error={error}
        showFeedback={!onFeedback}
        restartBehavior={restartBehavior}
        restartResult={restartResult}
        stopSucceeded={stopMutation.isSuccess}
      />
    </div>
  );
}

function RunActionStatus({
  error,
  showFeedback,
  restartBehavior,
  restartResult,
  stopSucceeded,
}: {
  error: Error | null;
  showFeedback: boolean;
  restartBehavior: "navigate" | "refresh";
  restartResult: RestartRunResult | undefined;
  stopSucceeded: boolean;
}) {
  return (
    <>
      {" "}
      {error && showFeedback ? (
        <p
          role="alert"
          className="max-w-64 text-right text-[11px] text-destructive"
        >
          {error.message}
        </p>
      ) : null}
      {restartBehavior === "refresh" && restartResult && showFeedback ? (
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
      ) : stopSucceeded && showFeedback ? (
        <p
          role="status"
          className="max-w-64 text-right text-[11px] text-text-secondary"
        >
          중지를 요청했습니다.
        </p>
      ) : null}
    </>
  );
}

function RestartRunAction({
  restartMutation,
  size,
  isPending,
}: {
  restartMutation: ReturnType<typeof useRunActions>["restartMutation"];
  size: "xs" | "sm";
  isPending: boolean;
}) {
  return (
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
  );
}

function DeleteRunAction({
  actionTargetLabel,
  run,
  deleteMutation,
  size,
  isPending,
}: {
  actionTargetLabel: string;
  run: CrawlRunSummary;
  deleteMutation: ReturnType<typeof useRunActions>["deleteMutation"];
  size: "xs" | "sm";
  isPending: boolean;
}) {
  return (
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
  );
}

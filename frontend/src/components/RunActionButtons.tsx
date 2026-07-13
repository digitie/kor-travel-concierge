"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2Icon, RotateCcwIcon, SquareIcon } from "lucide-react";

import {
  restartRun,
  stopRun,
  type CrawlRunSummary,
  type RestartRunResult,
} from "@/lib/api";
import { isTerminalRun } from "@/lib/display-labels";
import { ConfirmActionButton } from "@/components/ConfirmActionButton";
import { Button } from "@/components/ui/button";

export type RunActionFeedback =
  | { kind: "stopped"; jobId: string }
  | { kind: "restarted"; jobId: string; created: boolean }
  | {
      kind: "error";
      action: "stop" | "restart";
      jobId: string;
      message: string;
    };

export function RunActionButtons({
  run,
  size = "xs",
  restartBehavior = "refresh",
  onFeedback,
}: {
  run: CrawlRunSummary;
  size?: "xs" | "sm";
  restartBehavior?: "navigate" | "refresh";
  onFeedback?: (feedback: RunActionFeedback) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const state = run.state.toLowerCase();

  async function invalidateRunQueries(jobIds: string[]) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["runs"] }),
      queryClient.invalidateQueries({ queryKey: ["run-queue"] }),
      ...jobIds.map((jobId) =>
        queryClient.invalidateQueries({ queryKey: ["run", jobId] }),
      ),
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

  const isPending = stopMutation.isPending || restartMutation.isPending;
  const error = stopMutation.error ?? restartMutation.error;
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

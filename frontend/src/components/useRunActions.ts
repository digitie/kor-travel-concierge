"use client";

import {
  deleteRun,
  restartRun,
  RUN_QUEUE_QUERY_KEY,
  stopRun,
  type CrawlRunSummary,
  type DeleteRunResult,
  type RestartRunResult,
} from "@/lib/api";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

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

type RunActionOptions = {
  run: CrawlRunSummary;
  restartBehavior: "navigate" | "refresh";
  onFeedback?: (feedback: RunActionFeedback) => void;
  onDeleted?: (jobId: string) => void;
};

export function useRunActions({
  run,
  restartBehavior,
  onFeedback,
  onDeleted,
}: RunActionOptions) {
  const router = useRouter();
  const queryClient = useQueryClient();

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
            queryClient.invalidateQueries({
              queryKey: ["run-video-stats", jobId],
            }),
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

  return {
    stopMutation,
    restartMutation,
    deleteMutation,
    isPending,
    error,
    restartResult,
  };
}

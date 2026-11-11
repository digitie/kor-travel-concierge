"use client";

import { type ReviewCandidatesKey } from "@/components/review/useReviewQueue";
import type { UnmatchedCandidate } from "@/lib/api";
import {
  ApiRequestError,
  getCandidateDetail,
  reopenCandidate,
} from "@/lib/api";
import {
  prepareCandidateReopenCaches,
  reconcileCandidateReopenCaches,
} from "@/lib/review-candidate-cache";
import {
  captureReviewUndoAttempt,
  classifyReviewUndoOutcome,
  dismissReviewUndo,
  isCurrentReviewUndoAttempt,
  type ReviewUndoState,
} from "@/lib/review-undo";
import type { QueryClient } from "@tanstack/react-query";
import { useMutation } from "@tanstack/react-query";
import { useCallback } from "react";

import type {
  ReopenCommand,
  ReopenRequestResult,
} from "./review-workspace-model";
import type { useCandidateDeleteWorkflow } from "./useCandidateDeleteWorkflow";
import type { useCandidateResolution } from "./useCandidateResolution";

export function useCandidateReopening({
  queryClient,
  setCandidateActionError,
  setReviewUndoError,
  queueScopeRef,
  selectionScopeEpochRef,
  selectedCandidateIdRef,
  detailIdRef,
  detailGenerationRef,
  reviewUndoStateRef,
  candidatesKeyRef,
  setSelectedCandidateSnapshot,
  markCandidateCacheRefreshError,
  updateReviewUndoState,
  setDetailId,
  navigateToReopenedCandidate,
}: {
  queryClient: QueryClient;
  setCandidateActionError: React.Dispatch<React.SetStateAction<string | null>>;
  setReviewUndoError: React.Dispatch<React.SetStateAction<string | null>>;
  queueScopeRef: React.RefObject<string>;
  selectionScopeEpochRef: React.RefObject<number>;
  selectedCandidateIdRef: React.RefObject<number | null>;
  detailIdRef: React.RefObject<number | null>;
  detailGenerationRef: React.RefObject<number>;
  reviewUndoStateRef: React.RefObject<ReviewUndoState>;
  candidatesKeyRef: React.RefObject<ReviewCandidatesKey>;
  setSelectedCandidateSnapshot: React.Dispatch<
    React.SetStateAction<UnmatchedCandidate | null>
  >;
  markCandidateCacheRefreshError: () => void;
  updateReviewUndoState: (
    update: (current: ReviewUndoState) => ReviewUndoState,
  ) => void;
  setDetailId: (
    next: number | null | ((current: number | null) => number | null),
  ) => void;
  navigateToReopenedCandidate: (candidate: UnmatchedCandidate) => void;
}) {
  const reopenMutation = useMutation({
    mutationFn: async (
      command: ReopenCommand,
    ): Promise<ReopenRequestResult> => {
      try {
        await prepareCandidateReopenCaches(
          queryClient,
          command.descriptor.candidate_id,
        );
        await reopenCandidate(command.descriptor);
        return { request: { kind: "success" }, error: null };
      } catch (error) {
        return {
          request: {
            kind: "error",
            status: error instanceof ApiRequestError ? error.status : null,
          },
          error,
        };
      }
    },
    onMutate: () => {
      setCandidateActionError(null);
      setReviewUndoError(null);
    },
    onSuccess: async (requestResult, command) => {
      const workflowIsCurrent = () =>
        command.queueScope === queueScopeRef.current &&
        command.workflowEpoch === selectionScopeEpochRef.current &&
        command.selectedCandidateId === selectedCandidateIdRef.current;
      const detailIsCurrent = () =>
        workflowIsCurrent() &&
        command.detailCandidateId === detailIdRef.current &&
        command.detailGeneration === detailGenerationRef.current;
      const completionIsCurrent = () =>
        command.source === "snackbar"
          ? Boolean(
              command.undoAttempt &&
                isCurrentReviewUndoAttempt(
                  reviewUndoStateRef.current,
                  command.undoAttempt,
                  queueScopeRef.current,
                  selectionScopeEpochRef.current,
                ),
            )
          : command.source === "detail"
            ? detailIsCurrent()
            : workflowIsCurrent();

      let reconciliation: Awaited<
        ReturnType<typeof reconcileCandidateReopenCaches>
      >;
      try {
        reconciliation = await reconcileCandidateReopenCaches(queryClient, {
          candidateId: command.descriptor.candidate_id,
          // UI completion 소유권과 cache healing은 별개다. 사용자가 선택/필터를
          // 바꿨어도 현재 active page는 commit 이후 exact snapshot으로 복구한다.
          activePageKey: candidatesKeyRef.current,
          fetchCandidateDetail: getCandidateDetail,
        });
      } catch (error) {
        reconciliation = {
          detail: { status: "error", error },
          canReselect: false,
          activePageRefreshed: false,
          refreshFailed: true,
        };
      }
      if (
        workflowIsCurrent() &&
        reconciliation.detail.status === "success" &&
        selectedCandidateIdRef.current === command.descriptor.candidate_id
      ) {
        setSelectedCandidateSnapshot(reconciliation.detail.detail.list_item);
      }
      if (reconciliation.refreshFailed && completionIsCurrent()) {
        markCandidateCacheRefreshError();
      }

      const classification = classifyReviewUndoOutcome({
        request: requestResult.request,
        authoritative: reconciliation.detail,
        expectedReviewState: command.expectedReviewState,
      });
      // snackbar state를 지우면 generation도 함께 바뀌므로, 완료 소유권은
      // dismiss 전에 한 번만 고정한다. 그렇지 않으면 성공/409 후속 UI가
      // 자기 자신을 stale 응답으로 오인한다.
      const completionWasCurrent = completionIsCurrent();
      const clearMatchingUndo = () => {
        updateReviewUndoState((current) => {
          const entry = current.current;
          return entry &&
            entry.descriptor.candidate_id === command.descriptor.candidate_id &&
            entry.descriptor.token === command.descriptor.token
            ? dismissReviewUndo(current)
            : current;
        });
      };

      if (classification === "restored" && reconciliation.canReselect) {
        clearMatchingUndo();
        setReviewUndoError(null);
        if (
          completionWasCurrent &&
          reconciliation.detail.status === "success"
        ) {
          setCandidateActionError(null);
          if (command.source === "detail") setDetailId(null);
          navigateToReopenedCandidate(reconciliation.detail.detail.list_item);
        }
        return;
      }

      if (classification === "stale") {
        clearMatchingUndo();
        setReviewUndoError(null);
        if (completionWasCurrent) {
          setCandidateActionError(
            `${command.candidateName} 후보는 다른 작업으로 상태가 바뀌어 이 복구 요청을 사용할 수 없습니다. 최신 목록에서 다시 확인해 주세요.`,
          );
        }
        return;
      }

      const errorMessage =
        classification === "retryable"
          ? "복구 결과를 확인하지 못했습니다. 같은 되돌리기 버튼으로 다시 시도해 주세요."
          : "복구 뒤 최신 후보 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.";
      if (!completionWasCurrent) return;
      if (command.source === "snackbar") {
        setReviewUndoError(errorMessage);
      } else {
        setCandidateActionError(`${command.candidateName}: ${errorMessage}`);
      }
    },
  });
  return { reopenMutation };
}

export function useCandidateReopenRequest({
  reopenMutation,
  resolveMutation,
  deleteCandidatesMutation,
  detailDeletePending,
  deepLinkValidationPending,
  setCandidateActionError,
  reviewUndoStateRef,
  queueScopeRef,
  selectionScopeEpochRef,
  selectedCandidateIdRef,
  detailIdRef,
  detailGenerationRef,
}: {
  reopenMutation: ReturnType<typeof useCandidateReopening>["reopenMutation"];
  resolveMutation: ReturnType<typeof useCandidateResolution>["resolveMutation"];
  deleteCandidatesMutation: ReturnType<
    typeof useCandidateDeleteWorkflow
  >["deleteCandidatesMutation"];
  detailDeletePending: boolean;
  deepLinkValidationPending: boolean;
  setCandidateActionError: React.Dispatch<React.SetStateAction<string | null>>;
  reviewUndoStateRef: React.RefObject<ReviewUndoState>;
  queueScopeRef: React.RefObject<string>;
  selectionScopeEpochRef: React.RefObject<number>;
  selectedCandidateIdRef: React.RefObject<number | null>;
  detailIdRef: React.RefObject<number | null>;
  detailGenerationRef: React.RefObject<number>;
}) {
  const requestCandidateReopen = useCallback(
    (
      candidate: Pick<
        UnmatchedCandidate,
        "id" | "ai_place_name" | "review_state" | "undo"
      >,
      source: ReopenCommand["source"],
    ) => {
      if (
        reopenMutation.isPending ||
        resolveMutation.isPending ||
        deleteCandidatesMutation.isPending ||
        detailDeletePending ||
        deepLinkValidationPending
      ) {
        return;
      }
      const restorableState = candidate.review_state !== "needs_review";
      if (
        !restorableState ||
        !candidate.undo ||
        candidate.undo.candidate_id !== candidate.id
      ) {
        setCandidateActionError(
          `${candidate.ai_place_name} 후보의 최신 복구 정보가 없습니다. 목록을 새로 불러와 주세요.`,
        );
        return;
      }
      const undoAttempt =
        source === "snackbar"
          ? captureReviewUndoAttempt(
              reviewUndoStateRef.current,
              queueScopeRef.current,
              selectionScopeEpochRef.current,
            )
          : null;
      if (source === "snackbar" && !undoAttempt) return;
      reopenMutation.mutate({
        descriptor: candidate.undo,
        candidateName: candidate.ai_place_name,
        expectedReviewState: candidate.review_state,
        source,
        undoAttempt,
        queueScope: queueScopeRef.current,
        workflowEpoch: selectionScopeEpochRef.current,
        selectedCandidateId: selectedCandidateIdRef.current,
        detailCandidateId: detailIdRef.current,
        detailGeneration: detailGenerationRef.current,
      });
    },
    [
      deepLinkValidationPending,
      detailDeletePending,
      reopenMutation,
      queueScopeRef,
      resolveMutation,
      deleteCandidatesMutation,
      setCandidateActionError,
      reviewUndoStateRef,
      selectionScopeEpochRef,
      selectedCandidateIdRef,
      detailIdRef,
      detailGenerationRef,
    ],
  );
  return { requestCandidateReopen };
}

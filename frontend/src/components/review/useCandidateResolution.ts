"use client";

import { type ReviewCandidatesKey } from "@/components/review/useReviewQueue";
import type { ResolveCandidateInput, UnmatchedCandidate } from "@/lib/api";
import { getCandidateDetail, resolveCandidate } from "@/lib/api";
import {
  reconcileProcessedCandidateCaches,
  revalidateCandidateActionFailure,
  type CandidateDetailRevalidation,
} from "@/lib/review-candidate-cache";
import {
  buildCreatePlaceResolution,
  parseNearbyPlaceConflict,
} from "@/lib/review-provenance";
import {
  applyReviewActionSuccess,
  reconcileReviewUndoAfterActionFailure,
  waitForCandidateOperationMarker,
  type ReviewUndoState,
} from "@/lib/review-undo";
import type { QueryClient } from "@tanstack/react-query";
import { useMutation } from "@tanstack/react-query";

import type {
  NearbyConflict,
  ResolveCommand,
  ResolveCommandDraft,
} from "./review-workspace-model";
import { CandidateResolveAttemptError } from "./review-workspace-model";

export function useCandidateResolution({
  isCurrentResolveCommand,
  setNearbyConflict,
  setCandidateActionError,
  candidatesKeyRef,
  queueScopeRef,
  queryClient,
  markCandidateCacheRefreshError,
  reviewUndoStateRef,
  updateReviewUndoState,
  setReviewUndoError,
  reconcileFailedCandidateSelection,
  cancelCategoryMatch,
  advanceAfterProcessing,
  removeCandidateSelections,
  clearProcessedCandidateParam,
  selectedCandidateIdRef,
  initialSelectionDoneRef,
  setQueueCompleted,
  setSelectedCandidateSnapshot,
  setSelectedId,
}: {
  isCurrentResolveCommand: (command: ResolveCommandDraft) => boolean;
  setNearbyConflict: React.Dispatch<
    React.SetStateAction<NearbyConflict | null>
  >;
  setCandidateActionError: React.Dispatch<React.SetStateAction<string | null>>;
  candidatesKeyRef: React.RefObject<ReviewCandidatesKey>;
  queueScopeRef: React.RefObject<string>;
  queryClient: QueryClient;
  markCandidateCacheRefreshError: () => void;
  reviewUndoStateRef: React.RefObject<ReviewUndoState>;
  updateReviewUndoState: (
    update: (current: ReviewUndoState) => ReviewUndoState,
  ) => void;
  setReviewUndoError: React.Dispatch<React.SetStateAction<string | null>>;
  reconcileFailedCandidateSelection: (
    candidateId: number,
    workflow: {
      visibleIndex: number;
      orderedCandidateIds: number[];
      loadedPageCount: number;
      queueScope: string;
      workflowEpoch: number;
      activePageKey: ReviewCandidatesKey;
    },
    detailRevalidation: CandidateDetailRevalidation | undefined,
  ) => boolean;
  cancelCategoryMatch: () => void;
  advanceAfterProcessing: (
    processedId: number,
    processedIds?: number[],
    visibleIndex?: number,
    orderedCandidateIds?: number[],
    loadedPageCount?: number,
  ) => void;
  removeCandidateSelections: (candidateIds: readonly number[]) => void;
  clearProcessedCandidateParam: (
    candidateId: number,
    preserveSelection?: boolean,
  ) => boolean;
  selectedCandidateIdRef: React.RefObject<number | null>;
  initialSelectionDoneRef: React.RefObject<boolean>;
  setQueueCompleted: React.Dispatch<React.SetStateAction<boolean>>;
  setSelectedCandidateSnapshot: React.Dispatch<
    React.SetStateAction<UnmatchedCandidate | null>
  >;
  setSelectedId: React.Dispatch<React.SetStateAction<number | null>>;
}) {
  const resolveMutation = useMutation({
    mutationFn: async (command: ResolveCommand) => {
      const input: ResolveCandidateInput =
        command.action === "ignore"
          ? {
              action: "ignore",
              expectedRevision: command.expectedRevision,
              clientOperationId: command.clientOperationId,
              reviewNote: "검수 페이지 제외",
            }
          : {
              ...buildCreatePlaceResolution(
                command.form,
                command.selectedHit,
                command.duplicate,
              ),
              expectedRevision: command.expectedRevision,
              clientOperationId: command.clientOperationId,
            };
      try {
        const response = await resolveCandidate(command.candidateId, input);
        const expectedReviewState =
          command.action === "ignore" ? "ignored" : "user_corrected";
        if (
          response.status !== "resolved" ||
          response.client_operation_id !== command.clientOperationId ||
          response.candidate.id !== command.candidateId ||
          response.candidate.review_state !== expectedReviewState ||
          response.candidate.state_revision <= command.expectedRevision ||
          response.candidate.last_client_operation_id !==
            command.clientOperationId ||
          response.candidate.undo?.candidate_id !== command.candidateId ||
          response.candidate.undo?.token !== response.undo.token ||
          response.undo.candidate_id !== command.candidateId ||
          response.undo.token.length === 0
        ) {
          throw new Error(
            "후보 처리 응답이 요청 후보의 완료 상태와 일치하지 않습니다.",
          );
        }
        return response;
      } catch (error) {
        throw new CandidateResolveAttemptError(error);
      }
    },
    onError: async (error, command) => {
      const requestAttempted = error instanceof CandidateResolveAttemptError;
      const requestStatus = requestAttempted ? error.requestStatus : null;
      const originalError = requestAttempted ? error.originalError : error;
      const conflict = parseNearbyPlaceConflict(originalError);
      const isCurrentCommand = isCurrentResolveCommand(command);
      if (conflict) {
        if (isCurrentCommand) {
          setNearbyConflict({ command, places: conflict });
        }
        return;
      }
      if (isCurrentCommand) {
        setCandidateActionError(
          `${command.candidateName} 후보 처리 결과를 확인하지 못했습니다: ${error.message}`,
        );
      }
      const activeCandidatesKey = candidatesKeyRef.current;
      const activeQueueScope = queueScopeRef.current;
      const failureRefresh = await revalidateCandidateActionFailure(
        queryClient,
        {
          candidateIds: [command.candidateId],
          activePageKey: activeCandidatesKey,
          fetchCandidateDetail: getCandidateDetail,
        },
      );
      if (
        failureRefresh.refreshFailed &&
        activeQueueScope === queueScopeRef.current
      ) {
        markCandidateCacheRefreshError();
      }
      const initialAuthoritative = failureRefresh.candidateDetails.get(
        command.candidateId,
      );
      const authoritative =
        requestAttempted && (requestStatus == null || requestStatus >= 500)
          ? await waitForCandidateOperationMarker({
              initial: initialAuthoritative,
              candidateId: command.candidateId,
              expectedReviewState:
                command.action === "ignore" ? "ignored" : "user_corrected",
              fetchCandidateDetail: getCandidateDetail,
            })
          : initialAuthoritative;
      if (authoritative?.status === "success") {
        queryClient.setQueryData(
          ["candidate-detail", command.candidateId],
          authoritative.detail,
        );
      }
      const undoReconciliation = reconcileReviewUndoAfterActionFailure(
        reviewUndoStateRef.current,
        {
          authoritative,
          requestAttempted,
          requestStatus,
          clientOperationId: command.clientOperationId,
          candidateId: command.candidateId,
          candidateName: command.candidateName,
          action: command.action,
          expectedReviewState:
            command.action === "ignore" ? "ignored" : "user_corrected",
        },
      );
      updateReviewUndoState(() => undoReconciliation.state);
      if (
        isCurrentCommand &&
        undoReconciliation.outcome === "confirmed_committed"
      ) {
        setCandidateActionError(
          `${command.candidateName} 후보의 응답은 끊겼지만 최신 상태에서 처리 완료를 확인했습니다.`,
        );
      } else if (
        isCurrentCommand &&
        undoReconciliation.outcome === "foreign_or_stale"
      ) {
        setCandidateActionError(
          `${command.candidateName} 후보는 다른 작업으로 상태가 바뀌어 최신 상태를 반영했습니다.`,
        );
      }
      if (
        authoritative?.status !== "success" ||
        authoritative.detail.list_item.review_state !== "needs_review"
      ) {
        setReviewUndoError(null);
      }
      reconcileFailedCandidateSelection(
        command.candidateId,
        {
          visibleIndex: command.visibleIndex,
          orderedCandidateIds: command.orderedCandidateIds,
          loadedPageCount: command.loadedPageCount,
          queueScope: command.queueScope,
          workflowEpoch: command.workflowEpoch,
          activePageKey: activeCandidatesKey,
        },
        authoritative,
      );
    },
    onSuccess: async (data, command) => {
      // 409 중복 확인 응답은 성공이 아니므로 여기까지 오지 않는다. 실제 확정 뒤에만
      // 큐에서 제거해 확인 다이얼로그가 뜰 때 후보가 사라졌다 복원되는 깜빡임을 막는다.
      const activeCandidatesKey = candidatesKeyRef.current;
      const activeQueueScope = queueScopeRef.current;
      const cacheResult = await reconcileProcessedCandidateCaches(queryClient, {
        ids: [command.candidateId],
        capturedPageKey: command.candidatesKey,
        activePageKey: activeCandidatesKey,
        pageOut: command.visibleIndex < 0,
      });
      if (
        cacheResult.postCommitRefreshFailed &&
        activeQueueScope === queueScopeRef.current
      ) {
        markCandidateCacheRefreshError();
      }
      queryClient.removeQueries({
        queryKey: ["candidate-detail", command.candidateId],
      });
      queryClient.invalidateQueries({ queryKey: ["destinations"] });
      if (command.action === "create_place") {
        queryClient.invalidateQueries({ queryKey: ["destination-facets"] });
      }
      // 저장·제외 모두 needs_review 후보를 큐에서 빼므로 provenance facet count를
      // 갱신한다(T-187).
      queryClient.invalidateQueries({ queryKey: ["review-source-facets"] });
      updateReviewUndoState((current) =>
        applyReviewActionSuccess(current, {
          candidateId: command.candidateId,
          candidateName: command.candidateName,
          action: command.action,
          reviewState: data.candidate.review_state,
          undo: data.undo,
        }),
      );
      setReviewUndoError(null);
      const isCurrentCommand = isCurrentResolveCommand(command);
      if (isCurrentCommand) {
        setNearbyConflict(null);
        setCandidateActionError(null);
      }
      if (isCurrentCommand && command.visibleIndex >= 0) {
        cancelCategoryMatch();
        advanceAfterProcessing(
          command.candidateId,
          [command.candidateId],
          command.visibleIndex,
          command.orderedCandidateIds,
          command.loadedPageCount,
        );
      } else {
        removeCandidateSelections([command.candidateId]);
        clearProcessedCandidateParam(command.candidateId, false);
        if (selectedCandidateIdRef.current === command.candidateId) {
          cancelCategoryMatch();
          initialSelectionDoneRef.current = false;
          selectedCandidateIdRef.current = null;
          setQueueCompleted(false);
          setSelectedCandidateSnapshot(null);
          setSelectedId(null);
        }
      }
    },
    onSettled: (_data, error, command) => {
      if (error) {
        queryClient.invalidateQueries({
          queryKey: command.candidatesKey,
          exact: true,
          refetchType: "none",
        });
      }
    },
  });
  return { resolveMutation };
}

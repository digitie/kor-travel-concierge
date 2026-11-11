"use client";

import { type ReviewCandidatesKey } from "@/components/review/useReviewQueue";
import type {
  DeleteCandidateResult,
  ListEnvelope,
  UnmatchedCandidate,
} from "@/lib/api";
import {
  ApiRequestError,
  deleteCandidate,
  getCandidateDetail,
} from "@/lib/api";
import {
  reconcileProcessedCandidateCaches,
  revalidateCandidateActionFailure,
  settleCandidateDeletes,
  type CandidateDetailRevalidation,
} from "@/lib/review-candidate-cache";
import { type ReviewListState } from "@/lib/review-list-state";
import {
  applyReviewActionSuccess,
  confirmCandidateDeleteDetail,
  deleteResponseMatchesConfirmedDetail,
  dismissReviewUndo,
  reconcileReviewUndoAfterActionFailure,
  waitForCandidateOperationMarker,
  type ReviewUndoState,
} from "@/lib/review-undo";
import type { QueryClient } from "@tanstack/react-query";
import { useMutation } from "@tanstack/react-query";

import type {
  DeleteCandidatesResult,
  DeleteCandidateTarget,
} from "./review-workspace-model";
import {
  candidateDeleteReconciliationRequestStatus,
  candidateFailureShouldAdvance,
  CandidateForwardAttemptError,
} from "./review-workspace-model";

export function useCandidateDeleteWorkflow({
  updateReviewUndoState,
  setReviewUndoError,
  candidatesKeyRef,
  queryClient,
  setCandidateActionError,
  selectedCandidateIdRef,
  candidates,
  candidatePages,
  queueScopeRef,
  selectionScopeEpochRef,
  markCandidateCacheRefreshError,
  removeCandidateSelections,
  reviewUndoStateRef,
  reviewListStateRef,
  reconcileFailedCandidateSelection,
  advanceAfterProcessing,
  clearProcessedCandidateParam,
  initialSelectionDoneRef,
  setQueueCompleted,
  setSelectedCandidateSnapshot,
  setSelectedId,
}: {
  updateReviewUndoState: (
    update: (current: ReviewUndoState) => ReviewUndoState,
  ) => void;
  setReviewUndoError: React.Dispatch<React.SetStateAction<string | null>>;
  candidatesKeyRef: React.RefObject<ReviewCandidatesKey>;
  queryClient: QueryClient;
  setCandidateActionError: React.Dispatch<React.SetStateAction<string | null>>;
  selectedCandidateIdRef: React.RefObject<number | null>;
  candidates: UnmatchedCandidate[];
  candidatePages: ListEnvelope<UnmatchedCandidate>[];
  queueScopeRef: React.RefObject<string>;
  selectionScopeEpochRef: React.RefObject<number>;
  markCandidateCacheRefreshError: () => void;
  removeCandidateSelections: (candidateIds: readonly number[]) => void;
  reviewUndoStateRef: React.RefObject<ReviewUndoState>;
  reviewListStateRef: React.RefObject<ReviewListState>;
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
  advanceAfterProcessing: (
    processedId: number,
    processedIds?: number[],
    visibleIndex?: number,
    orderedCandidateIds?: number[],
    loadedPageCount?: number,
  ) => void;
  clearProcessedCandidateParam: (
    candidateId: number,
    preserveSelection?: boolean,
  ) => boolean;
  initialSelectionDoneRef: React.RefObject<boolean>;
  setQueueCompleted: React.Dispatch<React.SetStateAction<boolean>>;
  setSelectedCandidateSnapshot: React.Dispatch<
    React.SetStateAction<UnmatchedCandidate | null>
  >;
  setSelectedId: React.Dispatch<React.SetStateAction<number | null>>;
}) {
  const deleteCandidatesMutation = useMutation({
    mutationFn: async (
      targets: DeleteCandidateTarget[],
    ): Promise<DeleteCandidatesResult> => {
      const targetById = new Map(targets.map((target) => [target.id, target]));
      const responses = new Map<number, DeleteCandidateResult>();
      const batch = await settleCandidateDeletes(
        targets.map((target) => target.id),
        async (candidateId) => {
          const target = targetById.get(candidateId);
          if (!target)
            throw new Error(`삭제 후보 #${candidateId} 정보가 없습니다.`);
          const clientOperationId = crypto.randomUUID();
          let responseReceived = false;
          let response: DeleteCandidateResult | null = null;
          try {
            response = await deleteCandidate(
              candidateId,
              target.state_revision,
              clientOperationId,
            );
            responseReceived = true;
            const firstDetail = await getCandidateDetail(candidateId);
            const authoritative = await waitForCandidateOperationMarker({
              initial: { status: "success", detail: firstDetail },
              candidateId,
              expectedReviewState: "deleted",
              fetchCandidateDetail: getCandidateDetail,
            });
            const confirmed =
              authoritative?.status === "success"
                ? confirmCandidateDeleteDetail({
                    detail: authoritative.detail,
                    candidateId,
                    expectedRevision: target.state_revision,
                    clientOperationId,
                  })
                : null;
            if (
              !confirmed ||
              !deleteResponseMatchesConfirmedDetail({
                response,
                confirmed,
                candidateId,
                clientOperationId,
              })
            ) {
              throw new Error(
                "삭제 응답이 요청 후보의 완료 상태와 일치하지 않습니다.",
              );
            }
            responses.set(candidateId, response);
          } catch (error) {
            throw new CandidateForwardAttemptError(
              error,
              clientOperationId,
              target.state_revision,
              responseReceived,
              response,
            );
          }
        },
      );
      return { ...batch, responses };
    },
    onMutate: async (targets) => {
      if (targets.length > 1) {
        updateReviewUndoState(dismissReviewUndo);
        setReviewUndoError(null);
      }
      const mutationCandidatesKey = candidatesKeyRef.current;
      await queryClient.cancelQueries({
        queryKey: mutationCandidatesKey,
        exact: true,
      });
      setCandidateActionError(null);
      const focusedId = selectedCandidateIdRef.current;
      return {
        candidatesKey: mutationCandidatesKey,
        focusedId,
        visibleIndex:
          focusedId == null
            ? -1
            : candidates.findIndex((candidate) => candidate.id === focusedId),
        orderedCandidateIds: candidates.map((candidate) => candidate.id),
        loadedPageCount: candidatePages.length,
        queueScope: queueScopeRef.current,
        workflowEpoch: selectionScopeEpochRef.current,
      };
    },
    onSuccess: async (result, targets, context) => {
      const activeCandidatesKey = candidatesKeyRef.current;
      const activeQueueScope = queueScopeRef.current;
      const pageOut =
        result.succeededIds.length > 0 &&
        context.focusedId != null &&
        result.succeededIds.includes(context.focusedId) &&
        context.visibleIndex < 0;
      const cacheResult = await reconcileProcessedCandidateCaches(queryClient, {
        ids: result.succeededIds,
        capturedPageKey: context.candidatesKey,
        activePageKey: activeCandidatesKey,
        pageOut,
      });
      if (
        cacheResult.postCommitRefreshFailed &&
        activeQueueScope === queueScopeRef.current
      ) {
        markCandidateCacheRefreshError();
      }
      removeCandidateSelections(result.succeededIds);
      if (result.succeededIds.length > 0) {
        const candidateId = result.succeededIds[0];
        const target = targets.find(
          (candidate) => candidate.id === candidateId,
        );
        const response = result.responses.get(candidateId);
        updateReviewUndoState((current) =>
          applyReviewActionSuccess(current, {
            candidateId,
            candidateName: target?.ai_place_name ?? `후보 #${candidateId}`,
            action: "delete",
            reviewState: "deleted",
            undo: response?.undo,
            processedCount: result.attemptedIds.length,
          }),
        );
        setReviewUndoError(null);
      }
      if (result.failures.length > 0) {
        const details = result.failures
          .map(
            ({ id, reason }) =>
              `#${id}: ${reason instanceof Error ? reason.message : "삭제 결과 불명"}`,
          )
          .join(", ");
        setCandidateActionError(
          `후보 ${result.succeededIds.length}개는 삭제했고 ${result.failures.length}개는 삭제 결과를 확인하지 못해 최신 상태를 다시 확인했습니다. ${details}`,
        );
        const failureRefresh = await revalidateCandidateActionFailure(
          queryClient,
          {
            candidateIds: result.failures.map(({ id }) => id),
            activePageKey: activeCandidatesKey,
            fetchCandidateDetail: getCandidateDetail,
          },
        );
        let retriedFailedId: number | undefined;
        let retriedAuthoritative: CandidateDetailRevalidation | undefined;
        if (result.attemptedIds.length === 1) {
          const failedId = result.failures[0]?.id;
          retriedFailedId = failedId;
          const target = targets.find((candidate) => candidate.id === failedId);
          const initialAuthoritative =
            failedId == null
              ? undefined
              : failureRefresh.candidateDetails.get(failedId);
          const failureReason = result.failures[0]?.reason;
          const requestAttempted =
            failureReason instanceof CandidateForwardAttemptError;
          const requestStatus =
            failureReason instanceof CandidateForwardAttemptError
              ? failureReason.requestStatus
              : failureReason instanceof ApiRequestError
                ? failureReason.status
                : null;
          const clientOperationId =
            failureReason instanceof CandidateForwardAttemptError
              ? failureReason.clientOperationId
              : null;
          const authoritative =
            failedId == null ||
            !requestAttempted ||
            (requestStatus != null && requestStatus < 500)
              ? initialAuthoritative
              : await waitForCandidateOperationMarker({
                  initial: initialAuthoritative,
                  candidateId: failedId,
                  expectedReviewState: "deleted",
                  fetchCandidateDetail: getCandidateDetail,
                });
          retriedAuthoritative = authoritative;
          if (failedId != null && authoritative?.status === "success") {
            queryClient.setQueryData(
              ["candidate-detail", failedId],
              authoritative.detail,
            );
          }
          const undoReconciliation = reconcileReviewUndoAfterActionFailure(
            reviewUndoStateRef.current,
            {
              authoritative,
              requestAttempted,
              requestStatus: candidateDeleteReconciliationRequestStatus(
                failureReason,
                authoritative,
                failedId ?? result.attemptedIds[0],
              ),
              clientOperationId,
              candidateId: failedId ?? result.attemptedIds[0],
              candidateName:
                target?.ai_place_name ??
                `후보 #${failedId ?? result.attemptedIds[0]}`,
              action: "delete",
              expectedReviewState: "deleted",
            },
          );
          updateReviewUndoState(() => undoReconciliation.state);
          if (undoReconciliation.outcome === "confirmed_committed") {
            setCandidateActionError(
              `${target?.ai_place_name ?? `후보 #${failedId}`} 후보의 응답은 끊겼지만 최신 상태에서 삭제 완료를 확인했습니다.`,
            );
          } else if (undoReconciliation.outcome === "foreign_or_stale") {
            setCandidateActionError(
              `${target?.ai_place_name ?? `후보 #${failedId}`} 후보는 다른 작업으로 상태가 바뀌어 최신 상태를 반영했습니다.`,
            );
          }
          if (
            authoritative?.status !== "success" ||
            authoritative.detail.list_item.review_state !== "needs_review"
          ) {
            setReviewUndoError(null);
          }
        }
        removeCandidateSelections(
          result.failures
            .map(({ id }) => id)
            .filter((candidateId) =>
              candidateFailureShouldAdvance(
                candidateId === retriedFailedId
                  ? retriedAuthoritative
                  : failureRefresh.candidateDetails.get(candidateId),
                reviewListStateRef.current,
              ),
            ),
        );
        if (
          failureRefresh.refreshFailed &&
          activeQueueScope === queueScopeRef.current
        ) {
          markCandidateCacheRefreshError();
        }
        if (
          context.focusedId != null &&
          result.failures.some(({ id }) => id === context.focusedId)
        ) {
          reconcileFailedCandidateSelection(
            context.focusedId,
            {
              visibleIndex: context.visibleIndex,
              orderedCandidateIds: context.orderedCandidateIds,
              loadedPageCount: context.loadedPageCount,
              queueScope: context.queueScope,
              workflowEpoch: context.workflowEpoch,
              activePageKey: activeCandidatesKey,
            },
            context.focusedId === retriedFailedId
              ? retriedAuthoritative
              : failureRefresh.candidateDetails.get(context.focusedId),
          );
        }
      }
      const focusedId = context.focusedId;
      const focusedCandidateProcessed =
        focusedId != null &&
        result.succeededIds.includes(focusedId) &&
        focusedId === selectedCandidateIdRef.current;
      if (focusedCandidateProcessed) {
        if (
          result.attemptedIds.length === 1 &&
          context.visibleIndex >= 0 &&
          context.queueScope === queueScopeRef.current &&
          context.workflowEpoch === selectionScopeEpochRef.current
        ) {
          advanceAfterProcessing(
            focusedId,
            result.succeededIds,
            context.visibleIndex,
            context.orderedCandidateIds,
            context.loadedPageCount,
          );
        } else {
          result.succeededIds.forEach((id) =>
            clearProcessedCandidateParam(id, false),
          );
          initialSelectionDoneRef.current = false;
          selectedCandidateIdRef.current = null;
          setQueueCompleted(false);
          setSelectedCandidateSnapshot(null);
          setSelectedId(null);
        }
      } else {
        result.succeededIds.forEach((id) =>
          clearProcessedCandidateParam(id, false),
        );
      }
    },
    onError: async (error, targets, context) => {
      const candidateIds = targets.map((candidate) => candidate.id);
      setCandidateActionError(
        `후보 삭제 결과를 확인하지 못했습니다: ${error.message}`,
      );
      const activeCandidatesKey = candidatesKeyRef.current;
      const activeQueueScope = queueScopeRef.current;
      const failureRefresh = await revalidateCandidateActionFailure(
        queryClient,
        {
          candidateIds,
          activePageKey: activeCandidatesKey,
          fetchCandidateDetail: getCandidateDetail,
        },
      );
      let singleAuthoritative: CandidateDetailRevalidation | undefined;
      if (candidateIds.length === 1) {
        const target = targets[0];
        const requestAttempted = error instanceof CandidateForwardAttemptError;
        const requestStatus =
          error instanceof CandidateForwardAttemptError
            ? error.requestStatus
            : error instanceof ApiRequestError
              ? error.status
              : null;
        const initialAuthoritative = failureRefresh.candidateDetails.get(
          candidateIds[0],
        );
        const authoritative =
          requestAttempted && (requestStatus == null || requestStatus >= 500)
            ? await waitForCandidateOperationMarker({
                initial: initialAuthoritative,
                candidateId: candidateIds[0],
                expectedReviewState: "deleted",
                fetchCandidateDetail: getCandidateDetail,
              })
            : initialAuthoritative;
        singleAuthoritative = authoritative;
        if (authoritative?.status === "success") {
          queryClient.setQueryData(
            ["candidate-detail", candidateIds[0]],
            authoritative.detail,
          );
        }
        const undoReconciliation = reconcileReviewUndoAfterActionFailure(
          reviewUndoStateRef.current,
          {
            authoritative,
            requestAttempted,
            requestStatus: candidateDeleteReconciliationRequestStatus(
              error,
              authoritative,
              candidateIds[0],
            ),
            clientOperationId:
              error instanceof CandidateForwardAttemptError
                ? error.clientOperationId
                : null,
            candidateId: candidateIds[0],
            candidateName: target?.ai_place_name ?? `후보 #${candidateIds[0]}`,
            action: "delete",
            expectedReviewState: "deleted",
          },
        );
        updateReviewUndoState(() => undoReconciliation.state);
        if (undoReconciliation.outcome === "confirmed_committed") {
          setCandidateActionError(
            `${target?.ai_place_name ?? `후보 #${candidateIds[0]}`} 후보의 응답은 끊겼지만 최신 상태에서 삭제 완료를 확인했습니다.`,
          );
        } else if (undoReconciliation.outcome === "foreign_or_stale") {
          setCandidateActionError(
            `${target?.ai_place_name ?? `후보 #${candidateIds[0]}`} 후보는 다른 작업으로 상태가 바뀌어 최신 상태를 반영했습니다.`,
          );
        }
        if (
          authoritative?.status !== "success" ||
          authoritative.detail.list_item.review_state !== "needs_review"
        ) {
          setReviewUndoError(null);
        }
      }
      removeCandidateSelections(
        candidateIds.filter((candidateId) =>
          candidateFailureShouldAdvance(
            candidateId === candidateIds[0] && singleAuthoritative
              ? singleAuthoritative
              : failureRefresh.candidateDetails.get(candidateId),
            reviewListStateRef.current,
          ),
        ),
      );
      if (
        failureRefresh.refreshFailed &&
        activeQueueScope === queueScopeRef.current
      ) {
        markCandidateCacheRefreshError();
      }
      if (
        context?.focusedId != null &&
        candidateIds.includes(context.focusedId)
      ) {
        reconcileFailedCandidateSelection(
          context.focusedId,
          {
            visibleIndex: context.visibleIndex,
            orderedCandidateIds: context.orderedCandidateIds,
            loadedPageCount: context.loadedPageCount,
            queueScope: context.queueScope,
            workflowEpoch: context.workflowEpoch,
            activePageKey: activeCandidatesKey,
          },
          context.focusedId === candidateIds[0] && singleAuthoritative
            ? singleAuthoritative
            : failureRefresh.candidateDetails.get(context.focusedId),
        );
      }
    },
  });
  return { deleteCandidatesMutation };
}

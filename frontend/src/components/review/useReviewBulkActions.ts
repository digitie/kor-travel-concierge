"use client";

import { type ReviewBulkIntent } from "@/components/ReviewBulkPanel";
import type { ReviewBulkScope } from "@/lib/api";
import { REVIEW_BULK_SELECTION_MAX } from "@/lib/api";
import {
  reviewListStateToForeignBulkFilter,
  type ReviewListState,
} from "@/lib/review-list-state";
import { dismissReviewUndo, type ReviewUndoState } from "@/lib/review-undo";
import { useReviewBulk } from "@/lib/use-review-bulk";
import type { QueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type Dispatch,
  type SetStateAction,
} from "react";

import { reviewBulkDialogState } from "./review-workspace-model";

export function useReviewBulkActions({
  setSelectedCandidateIds,
  updateReviewUndoState,
  setReviewUndoError,
  queryClient,
  restartCandidateSnapshot,
  queueScope,
  setCandidateActionError,
  selectedBulkCandidateIds,
  reviewListStateRef,
}: {
  setSelectedCandidateIds: (action: SetStateAction<number[]>) => void;
  updateReviewUndoState: (
    update: (current: ReviewUndoState) => ReviewUndoState,
  ) => void;
  setReviewUndoError: Dispatch<SetStateAction<string | null>>;
  queryClient: QueryClient;
  restartCandidateSnapshot: () => Promise<void>;
  queueScope: string;
  setCandidateActionError: (action: SetStateAction<string | null>) => void;
  selectedBulkCandidateIds: number[];
  reviewListStateRef: React.RefObject<ReviewListState>;
}) {
  const handleReviewBulkSettled = useCallback(async () => {
    setSelectedCandidateIds([]);
    updateReviewUndoState(dismissReviewUndo);
    setReviewUndoError(null);
    // 현재 scope는 첫 page부터 다시 열고, 다른 status/filter cache도 stale로
    // 표시해 다음 방문 때 bulk 이전 행을 재사용하지 않는다.
    await queryClient.invalidateQueries({
      queryKey: ["unmatched-candidates"],
      refetchType: "none",
    });
    await restartCandidateSnapshot();
  }, [
    queryClient,
    restartCandidateSnapshot,
    setReviewUndoError,
    setSelectedCandidateIds,
    updateReviewUndoState,
  ]);
  const {
    state: reviewBulkState,
    dialogOpen: reviewBulkDialogOpen,
    setDialogOpen: setReviewBulkDialogOpen,
    requestPreview: requestReviewBulkPreview,
    confirm: confirmReviewBulk,
    retry: retryReviewBulk,
    cancelUnconfirmed: cancelUnconfirmedReviewBulk,
    reset: resetReviewBulkWorkflow,
  } = useReviewBulk({ onSettled: handleReviewBulkSettled });
  const previousReviewBulkQueueScopeRef = useRef(queueScope);
  useEffect(() => {
    if (previousReviewBulkQueueScopeRef.current === queueScope) return;
    previousReviewBulkQueueScopeRef.current = queueScope;
    // 확인 전 preview만 현재 URL filter와 함께 폐기한다. 사용자가 이미 확인한
    // operation은 서버에 고정된 membership으로 filter 이동 뒤에도 끝까지 진행한다.
    cancelUnconfirmedReviewBulk();
  }, [cancelUnconfirmedReviewBulk, queueScope]);
  const bulkDialogState = useMemo(
    () => reviewBulkDialogState(reviewBulkState),
    [reviewBulkState],
  );
  const bulkBlocksCandidateActions =
    reviewBulkState.status === "previewing" ||
    reviewBulkState.status === "confirm" ||
    reviewBulkState.status === "executing" ||
    reviewBulkState.status === "expired" ||
    reviewBulkState.status === "error";
  const updateReviewBulkDialogOpen = useCallback(
    (open: boolean) => {
      if (
        !open &&
        (reviewBulkState.status === "previewing" ||
          reviewBulkState.status === "confirm" ||
          (reviewBulkState.status === "expired" &&
            reviewBulkState.progress == null) ||
          (reviewBulkState.status === "error" &&
            reviewBulkState.phase === "preview"))
      ) {
        // 확인 전 닫기/취소는 단순히 dialog만 숨기지 않는다. old draft와 token을
        // 폐기해야 selection 또는 URL filter를 바꾼 뒤 재시도가 옛 범위를 되살리지 않는다.
        cancelUnconfirmedReviewBulk();
        return;
      }
      if (
        !open &&
        reviewBulkState.status === "expired" &&
        reviewBulkState.progress != null
      ) {
        resetReviewBulkWorkflow();
        void handleReviewBulkSettled();
        return;
      }
      if (
        !open &&
        (reviewBulkState.status === "completed" ||
          reviewBulkState.status === "partial")
      ) {
        // 완료/부분 완료 결과는 닫는 즉시 폐기한다. 목록 refresh는 execute driver가
        // 이미 시작했으므로 중복 요청하지 않고 새 선택 status가 즉시 정본이 되게 한다.
        resetReviewBulkWorkflow();
        return;
      }
      if (
        !open &&
        reviewBulkState.status === "error" &&
        reviewBulkState.phase === "terminal"
      ) {
        resetReviewBulkWorkflow();
        void handleReviewBulkSettled();
        return;
      }
      setReviewBulkDialogOpen(open);
    },
    [
      cancelUnconfirmedReviewBulk,
      handleReviewBulkSettled,
      reviewBulkState,
      resetReviewBulkWorkflow,
      setReviewBulkDialogOpen,
    ],
  );
  const beginReviewBulk = useCallback(
    (intent: ReviewBulkIntent) => {
      setCandidateActionError(null);
      if (intent.scope === "selection") {
        if (selectedBulkCandidateIds.length === 0) {
          setCandidateActionError("일괄 처리할 후보를 먼저 선택해 주세요.");
          return;
        }
        if (selectedBulkCandidateIds.length > REVIEW_BULK_SELECTION_MAX) {
          setCandidateActionError(
            `직접 선택 작업은 최대 ${REVIEW_BULK_SELECTION_MAX}건입니다. 선택을 줄이거나 서버 필터 전체 작업을 사용해 주세요.`,
          );
          return;
        }
        try {
          requestReviewBulkPreview(intent.action, {
            kind: "selection",
            candidateIds: selectedBulkCandidateIds,
          });
        } catch (error) {
          setCandidateActionError(
            error instanceof Error
              ? error.message
              : "일괄 처리 범위를 만들지 못했습니다.",
          );
        }
        return;
      }
      try {
        requestReviewBulkPreview("ignore", {
          kind: "filter",
          filter: reviewListStateToForeignBulkFilter(
            reviewListStateRef.current,
          ),
        });
      } catch (error) {
        setCandidateActionError(
          error instanceof Error
            ? error.message
            : "일괄 처리 범위를 만들지 못했습니다.",
        );
      }
    },
    [
      requestReviewBulkPreview,
      reviewListStateRef,
      selectedBulkCandidateIds,
      setCandidateActionError,
    ],
  );
  const startConfirmedReviewBulk = useCallback(() => {
    updateReviewUndoState(dismissReviewUndo);
    setReviewUndoError(null);
    confirmReviewBulk();
  }, [confirmReviewBulk, setReviewUndoError, updateReviewUndoState]);
  const retryVisibleReviewBulk = useCallback(() => {
    if (
      reviewBulkState.status === "expired" &&
      reviewBulkState.progress != null
    ) {
      // 일부 chunk가 반영된 operation은 오래된 전체 scope로 되돌리지 않는다.
      // token-free 결과만 남기고 최신 목록에서 실제 잔여 대상을 다시 고르게 한다.
      resetReviewBulkWorkflow();
      void handleReviewBulkSettled();
      return;
    }
    if (reviewBulkState.status !== "partial") {
      retryReviewBulk();
      return;
    }
    const failedIds = Array.from(
      new Set(
        reviewBulkState.progress.failed.map((issue) => issue.candidate_id),
      ),
    );
    if (failedIds.length === 0) {
      // conflict는 현재 action과 이미 호환되지 않을 수 있으므로 어떤 scope에서도
      // 자동 재실행하지 않는다. 이미 시작된 settle refresh의 새 목록에서 재선택한다.
      resetReviewBulkWorkflow();
      return;
    }
    if (failedIds.length > REVIEW_BULK_SELECTION_MAX) {
      setCandidateActionError(
        `처리 실패가 ${failedIds.length.toLocaleString("ko-KR")}건이라 한 번에 다시 확인할 수 없습니다. 목록을 새로고침한 뒤 ${REVIEW_BULK_SELECTION_MAX}건씩 나누어 선택해 주세요.`,
      );
      resetReviewBulkWorkflow();
      return;
    }
    // 원래 filter 작업이어도 failed ID만 명시 selection으로 고정한다. 원래 filter를
    // 다시 쓰면 revision conflict와 새 후보까지 자동 실행 범위에 섞일 수 있다.
    const scope: ReviewBulkScope = {
      kind: "selection",
      candidateIds: failedIds,
    };
    try {
      requestReviewBulkPreview(reviewBulkState.draft.action, scope);
    } catch (error) {
      setCandidateActionError(
        error instanceof Error
          ? error.message
          : "처리되지 않은 후보의 최신 범위를 만들지 못했습니다.",
      );
    }
  }, [
    handleReviewBulkSettled,
    requestReviewBulkPreview,
    resetReviewBulkWorkflow,
    retryReviewBulk,
    reviewBulkState,
    setCandidateActionError,
  ]);
  const abandonVisibleReviewBulk = useCallback(() => {
    const needsRefresh =
      (reviewBulkState.status === "expired" &&
        reviewBulkState.progress != null) ||
      (reviewBulkState.status === "error" &&
        reviewBulkState.phase !== "preview");
    resetReviewBulkWorkflow();
    if (needsRefresh) void handleReviewBulkSettled();
  }, [handleReviewBulkSettled, resetReviewBulkWorkflow, reviewBulkState]);
  return {
    reviewBulkDialogOpen,
    bulkDialogState,
    bulkBlocksCandidateActions,
    updateReviewBulkDialogOpen,
    beginReviewBulk,
    startConfirmedReviewBulk,
    retryVisibleReviewBulk,
    abandonVisibleReviewBulk,
  };
}

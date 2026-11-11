"use client";

import {
  applyReviewActionSuccess,
  INITIAL_REVIEW_UNDO_STATE,
  parseReviewUndoHandoff,
  REVIEW_UNDO_HANDOFF_STORAGE_KEY,
  type ReviewUndoState,
} from "@/lib/review-undo";
import { useCallback, useEffect, useRef, useState } from "react";

export function useReviewUndoState() {
  const [reviewUndoState, setReviewUndoState] = useState<ReviewUndoState>(
    INITIAL_REVIEW_UNDO_STATE,
  );
  const reviewUndoStateRef = useRef(reviewUndoState);
  const [reviewUndoError, setReviewUndoError] = useState<string | null>(null);
  const updateReviewUndoState = useCallback(
    (update: (current: ReviewUndoState) => ReviewUndoState) => {
      const next = update(reviewUndoStateRef.current);
      reviewUndoStateRef.current = next;
      setReviewUndoState(next);
    },
    [],
  );
  useEffect(() => {
    try {
      const serialized = window.sessionStorage.getItem(
        REVIEW_UNDO_HANDOFF_STORAGE_KEY,
      );
      window.sessionStorage.removeItem(REVIEW_UNDO_HANDOFF_STORAGE_KEY);
      const handoff = parseReviewUndoHandoff(serialized);
      if (!handoff) return;
      updateReviewUndoState((current) =>
        applyReviewActionSuccess(current, handoff),
      );
    } catch {
      // sessionStorage 비활성/오염은 현재 검수 큐 동작을 막지 않는다.
    }
  }, [updateReviewUndoState]);
  return {
    reviewUndoState,
    reviewUndoStateRef,
    reviewUndoError,
    setReviewUndoError,
    updateReviewUndoState,
  };
}

export function useReviewCacheStatus() {
  const [candidateCacheRefreshError, setCandidateCacheRefreshError] = useState<
    string | null
  >(null);
  const candidateCacheRefreshGenerationRef = useRef(0);
  const markCandidateCacheRefreshError = useCallback(() => {
    candidateCacheRefreshGenerationRef.current += 1;
    setCandidateCacheRefreshError(
      "최신 검수 상태를 다시 확인하지 못했습니다. 목록을 새로 불러와 주세요.",
    );
  }, []);
  const clearCandidateCacheRefreshError = useCallback(() => {
    candidateCacheRefreshGenerationRef.current += 1;
    setCandidateCacheRefreshError(null);
  }, []);
  return {
    candidateCacheRefreshError,
    candidateCacheRefreshGenerationRef,
    markCandidateCacheRefreshError,
    clearCandidateCacheRefreshError,
  };
}

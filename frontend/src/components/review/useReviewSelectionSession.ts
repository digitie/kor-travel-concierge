"use client";

import { type ReviewCandidatesKey } from "@/components/review/useReviewQueue";
import type {
  CandidateDetail,
  ListEnvelope,
  UnmatchedCandidate,
} from "@/lib/api";
import { getCandidateDetail, REVIEW_BULK_SELECTION_MAX } from "@/lib/api";
import {
  isReviewCandidateActionable,
  parseReviewCandidateId,
  type ReviewListState,
} from "@/lib/review-list-state";
import type {
  InfiniteData,
  UseInfiniteQueryResult,
  UseQueryResult,
} from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import { useStore } from "zustand";
import { useShallow } from "zustand/react/shallow";

import type {
  PendingCandidateAdvance,
  ReviewUi,
} from "./review-workspace-model";
import {
  recoveryCandidateAuthority,
  reviewCandidateAccess,
} from "./review-workspace-model";

export function useReviewQueueSelection({
  ui,
  candidates,
  reviewSearchParams,
  isRemovedView,
}: {
  ui: ReviewUi;
  candidates: UnmatchedCandidate[];
  reviewSearchParams: URLSearchParams;
  isRemovedView: boolean;
}) {
  const { selectedCandidateIds } = useStore(
    ui.store,
    useShallow((state) => ({
      selectedCandidateIds: state.selectedCandidateIds,
    })),
  );
  const { setSelectedCandidateIds } = ui.actions;

  const loadedCandidateIds = useMemo(
    () => new Set(candidates.map((candidate) => candidate.id)),
    [candidates],
  );
  const deepLinkedCandidateId = parseReviewCandidateId(reviewSearchParams);
  const deepLinkDetailQuery = useQuery({
    queryKey: ["candidate-detail", deepLinkedCandidateId],
    queryFn: () => getCandidateDetail(deepLinkedCandidateId as number),
    enabled: deepLinkedCandidateId != null,
    retry: false,
  });
  const deepLinkDetail = deepLinkDetailQuery.data ?? null;
  const deepLinkItem = deepLinkDetail?.list_item ?? null;
  const bulkSelectableLoadedCandidates = useMemo(
    () =>
      isRemovedView
        ? candidates.filter(
            (candidate) =>
              candidate.review_state !== "needs_review" &&
              candidate.undo?.candidate_id === candidate.id,
          )
        : candidates.filter((candidate) =>
            isReviewCandidateActionable(
              deepLinkItem?.id === candidate.id ? deepLinkItem : candidate,
            ),
          ),
    [candidates, deepLinkItem, isRemovedView],
  );
  const bulkSelectableLoadedCandidateIds = useMemo(
    () =>
      new Set(bulkSelectableLoadedCandidates.map((candidate) => candidate.id)),
    [bulkSelectableLoadedCandidates],
  );
  const selectedBulkCandidateIds = useMemo(
    () =>
      selectedCandidateIds.filter((candidateId) =>
        bulkSelectableLoadedCandidateIds.has(candidateId),
      ),
    [bulkSelectableLoadedCandidateIds, selectedCandidateIds],
  );
  const selectedCandidateSet = useMemo(
    () => new Set(selectedBulkCandidateIds),
    [selectedBulkCandidateIds],
  );
  const allLoadedCandidatesSelected =
    bulkSelectableLoadedCandidates.length > 0 &&
    bulkSelectableLoadedCandidates.every((candidate) =>
      selectedCandidateSet.has(candidate.id),
    );
  const someLoadedCandidatesSelected = selectedBulkCandidateIds.length > 0;
  const bulkSelectionLimitReached =
    selectedBulkCandidateIds.length >= REVIEW_BULK_SELECTION_MAX;
  const toggleCandidateSelection = useCallback(
    (candidateId: number) => {
      setSelectedCandidateIds((current) => {
        if (current.includes(candidateId)) {
          return current.filter((id) => id !== candidateId);
        }
        const currentSelectable = current.filter((id) =>
          bulkSelectableLoadedCandidateIds.has(id),
        );
        if (currentSelectable.length >= REVIEW_BULK_SELECTION_MAX) {
          return current;
        }
        return [...currentSelectable, candidateId];
      });
    },
    [bulkSelectableLoadedCandidateIds, setSelectedCandidateIds],
  );
  const removeCandidateSelections = useCallback(
    (candidateIds: readonly number[]) => {
      if (candidateIds.length === 0) return;
      const removed = new Set(candidateIds);
      setSelectedCandidateIds((current) =>
        current.filter((candidateId) => !removed.has(candidateId)),
      );
    },
    [setSelectedCandidateIds],
  );
  function toggleAllLoadedCandidates() {
    setSelectedCandidateIds((current) => {
      const currentSelectable = current.filter((id) =>
        bulkSelectableLoadedCandidateIds.has(id),
      );
      const targetCount = Math.min(
        bulkSelectableLoadedCandidates.length,
        REVIEW_BULK_SELECTION_MAX,
      );
      if (currentSelectable.length >= targetCount) {
        return current.filter(
          (id) => !bulkSelectableLoadedCandidateIds.has(id),
        );
      }
      const selected = new Set(currentSelectable);
      const additions = bulkSelectableLoadedCandidates
        .map((candidate) => candidate.id)
        .filter((candidateId) => !selected.has(candidateId))
        .slice(0, REVIEW_BULK_SELECTION_MAX - currentSelectable.length);
      return [...currentSelectable, ...additions];
    });
  }
  return {
    setSelectedCandidateIds,
    loadedCandidateIds,
    deepLinkedCandidateId,
    deepLinkDetailQuery,
    deepLinkDetail,
    deepLinkItem,
    bulkSelectableLoadedCandidateIds,
    selectedBulkCandidateIds,
    selectedCandidateSet,
    allLoadedCandidatesSelected,
    someLoadedCandidatesSelected,
    bulkSelectionLimitReached,
    toggleCandidateSelection,
    removeCandidateSelections,
    toggleAllLoadedCandidates,
  };
}

export function useReviewSelectionSession(ui: ReviewUi) {
  const {
    selectedId,
    selectedCandidateSnapshot,
    deepLinkValidationPending,
    deepLinkNotFound,
    pendingCandidateAdvance,
    queueCompleted,
    candidateActionError,
  } = useStore(
    ui.store,
    useShallow((state) => ({
      selectedId: state.selectedId,
      selectedCandidateSnapshot: state.selectedCandidateSnapshot,
      deepLinkValidationPending: state.deepLinkValidationPending,
      deepLinkNotFound: state.deepLinkNotFound,
      pendingCandidateAdvance: state.pendingCandidateAdvance,
      queueCompleted: state.queueCompleted,
      candidateActionError: state.candidateActionError,
    })),
  );
  const {
    setSelectedId,
    setSelectedCandidateSnapshot,
    setDeepLinkValidationPending,
    setDeepLinkNotFound,
    setPendingCandidateAdvance,
    setQueueCompleted,
    setCandidateActionError,
  } = ui.actions;

  const selectionScopeEpochRef = useRef(0);
  const validationGenerationRef = useRef(0);

  const invalidateCandidateWorkflow = useCallback(() => {
    selectionScopeEpochRef.current += 1;
    validationGenerationRef.current += 1;
    setDeepLinkValidationPending(false);
  }, [setDeepLinkValidationPending]);
  const initialSelectionDoneRef = useRef(false);

  const previousDeepLinkIdRef = useRef<number | null>(null);
  const preserveSelectionOnDeepLinkClearRef = useRef(false);
  const pendingCandidateAdvanceRef = useRef<PendingCandidateAdvance | null>(
    null,
  );

  const updatePendingCandidateAdvance = useCallback(
    (pending: PendingCandidateAdvance | null) => {
      const current = pendingCandidateAdvanceRef.current;
      if (
        current?.anchorIndex === pending?.anchorIndex &&
        current?.loadedPageCount === pending?.loadedPageCount &&
        current?.processedIds.length === pending?.processedIds.length &&
        current?.processedIds.every(
          (id, index) => id === pending?.processedIds[index],
        ) &&
        current?.orderedCandidateIds.length ===
          pending?.orderedCandidateIds.length &&
        current?.orderedCandidateIds.every(
          (id, index) => id === pending?.orderedCandidateIds[index],
        )
      ) {
        return;
      }
      if (current == null && pending == null) return;
      pendingCandidateAdvanceRef.current = pending;
      setPendingCandidateAdvance(pending);
    },
    [setPendingCandidateAdvance],
  );

  return {
    selectedId,
    setSelectedId,
    selectedCandidateSnapshot,
    setSelectedCandidateSnapshot,
    selectionScopeEpochRef,
    validationGenerationRef,
    deepLinkValidationPending,
    setDeepLinkValidationPending,
    invalidateCandidateWorkflow,
    initialSelectionDoneRef,
    deepLinkNotFound,
    setDeepLinkNotFound,
    previousDeepLinkIdRef,
    preserveSelectionOnDeepLinkClearRef,
    pendingCandidateAdvance,
    updatePendingCandidateAdvance,
    queueCompleted,
    setQueueCompleted,
    candidateActionError,
    setCandidateActionError,
  };
}

export function useCandidateDetailState() {
  const [detailId, setDetailIdState] = useState<number | null>(null);
  const detailIdRef = useRef<number | null>(null);
  const detailGenerationRef = useRef(0);
  const setDetailId = useCallback(
    (next: number | null | ((current: number | null) => number | null)) => {
      const resolved =
        typeof next === "function" ? next(detailIdRef.current) : next;
      if (resolved === detailIdRef.current) return;
      detailIdRef.current = resolved;
      detailGenerationRef.current += 1;
      setDetailIdState(resolved);
    },
    [],
  );
  const [detailDeletePending, setDetailDeletePending] = useState(false);
  const detailDeleteSnapshotRef = useRef<{
    candidateId: number;
    visibleIndex: number;
    orderedCandidateIds: number[];
    loadedPageCount: number;
    queueScope: string;
    workflowEpoch: number;
    candidatesKey: ReviewCandidatesKey;
  } | null>(null);
  return {
    detailId,
    detailIdRef,
    detailGenerationRef,
    setDetailId,
    detailDeletePending,
    setDetailDeletePending,
    detailDeleteSnapshotRef,
  };
}

export function useCandidateEditorState({
  ui,
  selected,
}: {
  ui: ReviewUi;
  selected: UnmatchedCandidate | null;
}) {
  const { form, formCandidateId, categoryEdited, selectedHit, nearbyConflict } =
    useStore(
      ui.store,
      useShallow((state) => ({
        form: state.form,
        formCandidateId: state.formCandidateId,
        categoryEdited: state.categoryEdited,
        selectedHit: state.selectedHit,
        nearbyConflict: state.nearbyConflict,
      })),
    );
  const {
    setForm,
    setFormCandidateId,
    setCategoryEdited,
    setSelectedHit,
    setNearbyConflict,
  } = ui.actions;

  const categoryMatchAbortRef = useRef<AbortController | null>(null);
  const categoryMatchRequestRef = useRef(0);
  const selectedCandidateIdRef = useRef<number | null>(selected?.id ?? null);
  return {
    form,
    setForm,
    formCandidateId,
    setFormCandidateId,
    categoryEdited,
    setCategoryEdited,
    selectedHit,
    setSelectedHit,
    nearbyConflict,
    setNearbyConflict,
    categoryMatchAbortRef,
    categoryMatchRequestRef,
    selectedCandidateIdRef,
  };
}

export function useAuthoritativeCandidate({
  selectedId,
  deepLinkedCandidateId,
  deepLinkItem,
  selectedCandidateSnapshot,
  candidates,
  reviewStatus,
  deepLinkDetail,
  reviewListState,
  loadedCandidateIds,
  isRemovedView,
  candidatesQuery,
  deepLinkDetailQuery,
}: {
  selectedId: number | null;
  deepLinkedCandidateId: number | null;
  deepLinkItem: UnmatchedCandidate | null;
  selectedCandidateSnapshot: UnmatchedCandidate | null;
  candidates: UnmatchedCandidate[];
  reviewStatus: "needs_review" | "removed";
  deepLinkDetail: CandidateDetail | null;
  reviewListState: ReviewListState;
  loadedCandidateIds: Set<number>;
  isRemovedView: boolean;
  candidatesQuery: UseInfiniteQueryResult<
    InfiniteData<ListEnvelope<UnmatchedCandidate>, unknown>,
    Error
  >;
  deepLinkDetailQuery: UseQueryResult<CandidateDetail, Error>;
}) {
  const selected = useMemo(() => {
    if (selectedId == null) return null;
    if (deepLinkedCandidateId != null) {
      return deepLinkItem?.id === selectedId ? deepLinkItem : null;
    }
    return (
      (selectedCandidateSnapshot?.id === selectedId
        ? selectedCandidateSnapshot
        : null) ??
      candidates.find((candidate) => candidate.id === selectedId) ??
      null
    );
  }, [
    candidates,
    deepLinkedCandidateId,
    deepLinkItem,
    selectedCandidateSnapshot,
    selectedId,
  ]);
  const recoveryDetailQuery = useQuery({
    queryKey: ["candidate-detail", selected?.id ?? null],
    queryFn: () => getCandidateDetail(selected?.id as number),
    enabled: Boolean(selected && selected.review_state !== "needs_review"),
  });
  const authoritativeRecoveryCandidate = useMemo(
    () =>
      recoveryCandidateAuthority(
        selected,
        recoveryDetailQuery.data,
        recoveryDetailQuery.isError,
        recoveryDetailQuery.isRefetchError,
      ),
    [
      selected,
      recoveryDetailQuery.data,
      recoveryDetailQuery.isError,
      recoveryDetailQuery.isRefetchError,
    ],
  );

  const {
    deepLinkStatusOut,
    deepLinkFilterOut,
    deepLinkLoadedOut,
    selectedActionable,
  } = reviewCandidateAccess({
    deepLinkItem,
    reviewStatus,
    deepLinkDetail,
    reviewListState,
    loadedCandidateIds,
    isRemovedView,
    selected,
    deepLinkedCandidateId,
    candidatesQuery,
    deepLinkDetailQuery,
  });
  return {
    selected,
    recoveryDetailQuery,
    authoritativeRecoveryCandidate,
    deepLinkStatusOut,
    deepLinkFilterOut,
    deepLinkLoadedOut,
    selectedActionable,
  };
}

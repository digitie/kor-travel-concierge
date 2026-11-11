"use client";

import { type ReviewCandidatesKey } from "@/components/review/useReviewQueue";
import type { ListEnvelope, UnmatchedCandidate } from "@/lib/api";
import {
  candidateFailureSelectionDecision,
  getCandidateFromReviewPageCache,
  type CandidateDetailRevalidation,
} from "@/lib/review-candidate-cache";
import { type ReviewListState } from "@/lib/review-list-state";
import { type SelectedPlaceHit } from "@/lib/review-provenance";
import type {
  InfiniteData,
  QueryClient,
  UseInfiniteQueryResult,
} from "@tanstack/react-query";
import { useCallback } from "react";
import type {
  CandidateSearchIntent,
  PrepareCandidateSearchOptions,
} from "./useCandidateSearch";

import type {
  NearbyConflict,
  PendingCandidateAdvance,
  ReviewUi,
} from "./review-workspace-model";
import {
  buildHintedQuery,
  candidateCategoryForm,
  candidateFailureShouldAdvance,
} from "./review-workspace-model";

export function useReviewCandidatePicker({
  ui,
  invalidateCandidateWorkflow,
  updatePendingCandidateAdvance,
  clearCandidateParam,
  initialSelectionDoneRef,
  selectedCandidateIdRef,
  setQueueCompleted,
  setSelectedCandidateSnapshot,
  setSelectedId,
  setQueryEdit,
  cancelCategoryMatch,
  setCategoryEdited,
  setSelectedHit,
  setNearbyConflict,
  setFormCandidateId,
  setForm,
  reviewListStateRef,
  prepareCandidate,
  queueScopeRef,
  selectionScopeEpochRef,
}: {
  ui: ReviewUi;
  invalidateCandidateWorkflow: () => void;
  updatePendingCandidateAdvance: (
    pending: PendingCandidateAdvance | null,
  ) => void;
  clearCandidateParam: (preserveSelection?: boolean) => void;
  initialSelectionDoneRef: React.RefObject<boolean>;
  selectedCandidateIdRef: React.RefObject<number | null>;
  setQueueCompleted: React.Dispatch<React.SetStateAction<boolean>>;
  setSelectedCandidateSnapshot: React.Dispatch<
    React.SetStateAction<UnmatchedCandidate | null>
  >;
  setSelectedId: React.Dispatch<React.SetStateAction<number | null>>;
  setQueryEdit: React.Dispatch<React.SetStateAction<string | null>>;
  cancelCategoryMatch: () => void;
  setCategoryEdited: React.Dispatch<React.SetStateAction<boolean>>;
  setSelectedHit: React.Dispatch<React.SetStateAction<SelectedPlaceHit | null>>;
  setNearbyConflict: React.Dispatch<
    React.SetStateAction<NearbyConflict | null>
  >;
  setFormCandidateId: React.Dispatch<React.SetStateAction<number | null>>;
  setForm: React.Dispatch<
    React.SetStateAction<{
      name: string;
      latitude: string;
      longitude: string;
      category: string;
      categoryCode: string;
    }>
  >;
  reviewListStateRef: React.RefObject<ReviewListState>;
  prepareCandidate: (
    intent: CandidateSearchIntent | null,
    options?: PrepareCandidateSearchOptions,
  ) => void;
  queueScopeRef: React.RefObject<string>;
  selectionScopeEpochRef: React.RefObject<number>;
}) {
  const pickCandidate = useCallback(
    (
      candidate: UnmatchedCandidate,
      {
        autoSearch = true,
        preserveWorkflow = false,
      }: { autoSearch?: boolean; preserveWorkflow?: boolean } = {},
    ) => {
      return ui.batch(() => {
        invalidateCandidateWorkflow();
        if (!preserveWorkflow) {
          updatePendingCandidateAdvance(null);
          clearCandidateParam(true);
          initialSelectionDoneRef.current = true;
        }
        const nextQuery = buildHintedQuery(candidate);
        selectedCandidateIdRef.current = candidate.id;
        setQueueCompleted(false);
        setSelectedCandidateSnapshot(candidate);
        setSelectedId(candidate.id);
        setQueryEdit(null);
        cancelCategoryMatch();
        setCategoryEdited(false);
        setSelectedHit(null);
        setNearbyConflict(null);
        setFormCandidateId(candidate.id);
        setForm({
          name: "",
          latitude: "",
          longitude: "",
          ...candidateCategoryForm(candidate),
        });
        const providerEnabled =
          autoSearch &&
          reviewListStateRef.current.status === "needs_review" &&
          candidate.review_state === "needs_review";
        prepareCandidate(
          {
            candidateId: candidate.id,
            requestIdentity: `${queueScopeRef.current}:${selectionScopeEpochRef.current}:${candidate.state_revision}`,
            query: nextQuery,
          },
          { autoSearch, providerEnabled },
        );
      });
    },
    [
      ui,
      invalidateCandidateWorkflow,
      selectedCandidateIdRef,
      setQueueCompleted,
      setSelectedCandidateSnapshot,
      setSelectedId,
      setQueryEdit,
      cancelCategoryMatch,
      setCategoryEdited,
      setSelectedHit,
      setNearbyConflict,
      setFormCandidateId,
      setForm,
      reviewListStateRef,
      prepareCandidate,
      queueScopeRef,
      selectionScopeEpochRef,
      updatePendingCandidateAdvance,
      clearCandidateParam,
      initialSelectionDoneRef,
    ],
  );
  return { pickCandidate };
}

export function useReviewCandidateAdvance({
  candidates,
  updatePendingCandidateAdvance,
  setQueueCompleted,
  pickCandidate,
  candidatePages,
  candidatePaginationContractError,
  candidatesQuery,
  setSelectedCandidateSnapshot,
  setSelectedId,
}: {
  candidates: UnmatchedCandidate[];
  updatePendingCandidateAdvance: (
    pending: PendingCandidateAdvance | null,
  ) => void;
  setQueueCompleted: React.Dispatch<React.SetStateAction<boolean>>;
  pickCandidate: (
    candidate: UnmatchedCandidate,
    options?: { autoSearch?: boolean; preserveWorkflow?: boolean },
  ) => void;
  candidatePages: ListEnvelope<UnmatchedCandidate>[];
  candidatePaginationContractError: string | null;
  candidatesQuery: UseInfiniteQueryResult<
    InfiniteData<ListEnvelope<UnmatchedCandidate>, unknown>,
    Error
  >;
  setSelectedCandidateSnapshot: React.Dispatch<
    React.SetStateAction<UnmatchedCandidate | null>
  >;
  setSelectedId: React.Dispatch<React.SetStateAction<number | null>>;
}) {
  const continueCandidateAdvance = useCallback(
    (plan: PendingCandidateAdvance) => {
      const processedIdSet = new Set(plan.processedIds);
      const remaining = candidates.filter(
        (candidate) => !processedIdSet.has(candidate.id),
      );
      const remainingById = new Map(
        remaining.map((candidate) => [candidate.id, candidate]),
      );
      const nextSnapshotId = plan.orderedCandidateIds
        .slice(plan.anchorIndex + 1)
        .find((candidateId) => remainingById.has(candidateId));
      const next =
        nextSnapshotId == null
          ? null
          : (remainingById.get(nextSnapshotId) ?? null);
      if (next) {
        updatePendingCandidateAdvance(null);
        setQueueCompleted(false);
        pickCandidate(next, { preserveWorkflow: true });
        return;
      }
      const newlyLoadedCandidate = candidatePages
        .slice(plan.loadedPageCount)
        .flatMap((page) => page.items)
        .find((candidate) => !processedIdSet.has(candidate.id));
      if (newlyLoadedCandidate) {
        updatePendingCandidateAdvance(null);
        setQueueCompleted(false);
        pickCandidate(newlyLoadedCandidate, { preserveWorkflow: true });
        return;
      }
      if (candidatePaginationContractError) {
        updatePendingCandidateAdvance(plan);
        return;
      }
      if (candidatesQuery.hasNextPage) {
        updatePendingCandidateAdvance(plan);
        if (
          !candidatesQuery.isFetchingNextPage &&
          !candidatesQuery.isFetchNextPageError
        ) {
          void candidatesQuery.fetchNextPage({ cancelRefetch: false });
        }
        return;
      }
      updatePendingCandidateAdvance(null);
      const previousSnapshotId = plan.orderedCandidateIds
        .slice(0, plan.anchorIndex)
        .reverse()
        .find((candidateId) => remainingById.has(candidateId));
      const previous =
        previousSnapshotId == null
          ? null
          : (remainingById.get(previousSnapshotId) ?? null);
      if (previous) {
        setQueueCompleted(false);
        pickCandidate(previous, { preserveWorkflow: true });
        return;
      }
      const firstRemaining = remaining[0] ?? null;
      if (firstRemaining) {
        setQueueCompleted(false);
        pickCandidate(firstRemaining, { preserveWorkflow: true });
        return;
      }
      setSelectedCandidateSnapshot(null);
      setSelectedId(null);
      setQueueCompleted(true);
    },
    [
      candidatesQuery,
      candidates,
      candidatePaginationContractError,
      candidatePages,
      pickCandidate,
      updatePendingCandidateAdvance,
      setQueueCompleted,
      setSelectedCandidateSnapshot,
      setSelectedId,
    ],
  );
  return { continueCandidateAdvance };
}

export function useFailedCandidateSelection({
  reviewListStateRef,
  selectedCandidateIdRef,
  queueScopeRef,
  selectionScopeEpochRef,
  removeCandidateSelections,
  queryClient,
  clearProcessedCandidateParam,
  setSelectedCandidateSnapshot,
  cancelCategoryMatch,
  initialSelectionDoneRef,
  setQueueCompleted,
  setSelectedId,
  advanceAfterProcessing,
}: {
  reviewListStateRef: React.RefObject<ReviewListState>;
  selectedCandidateIdRef: React.RefObject<number | null>;
  queueScopeRef: React.RefObject<string>;
  selectionScopeEpochRef: React.RefObject<number>;
  removeCandidateSelections: (candidateIds: readonly number[]) => void;
  queryClient: QueryClient;
  clearProcessedCandidateParam: (
    candidateId: number,
    preserveSelection?: boolean,
  ) => boolean;
  setSelectedCandidateSnapshot: React.Dispatch<
    React.SetStateAction<UnmatchedCandidate | null>
  >;
  cancelCategoryMatch: () => void;
  initialSelectionDoneRef: React.RefObject<boolean>;
  setQueueCompleted: React.Dispatch<React.SetStateAction<boolean>>;
  setSelectedId: React.Dispatch<React.SetStateAction<number | null>>;
  advanceAfterProcessing: (
    processedId: number,
    processedIds?: number[],
    visibleIndex?: number,
    orderedCandidateIds?: number[],
    loadedPageCount?: number,
  ) => void;
}) {
  const reconcileFailedCandidateSelection = useCallback(
    (
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
    ) => {
      const failureDecision = candidateFailureShouldAdvance(
        detailRevalidation,
        reviewListStateRef.current,
      )
        ? "advance"
        : "keep";
      const selectionDecision = candidateFailureSelectionDecision({
        failureDecision,
        candidateId,
        currentCandidateId: selectedCandidateIdRef.current,
      });
      const isCurrentWorkflow =
        workflow.queueScope === queueScopeRef.current &&
        workflow.workflowEpoch === selectionScopeEpochRef.current;

      if (selectionDecision !== "keep") {
        // workflow가 바뀌어도 처리 완료가 확인된 A의 raw checkbox와 상세 cache는
        // 제거한다. 현재 B를 보고 있다면 B의 선택/snapshot은 건드리지 않는다.
        removeCandidateSelections([candidateId]);
        queryClient.removeQueries({
          queryKey: ["candidate-detail", candidateId],
          exact: true,
        });
      }
      if (selectionDecision === "cleanup_candidate") {
        clearProcessedCandidateParam(candidateId, true);
        return false;
      }

      if (selectionDecision === "keep") {
        if (
          candidateId !== selectedCandidateIdRef.current ||
          !isCurrentWorkflow
        ) {
          return false;
        }
        const latestPageCandidate = getCandidateFromReviewPageCache(
          queryClient,
          workflow.activePageKey,
          candidateId,
        );
        if (detailRevalidation?.status === "success") {
          // 앞선 후보의 reopen 등으로 active page 밖으로 밀렸더라도 단건 상세가 현재
          // filter의 검수 대기 후보임을 증명하면 선택과 최신 snapshot을 유지한다.
          setSelectedCandidateSnapshot(detailRevalidation.detail.list_item);
        } else if (latestPageCandidate) {
          setSelectedCandidateSnapshot(latestPageCandidate);
        }
        return false;
      }

      // 단건 상세 404 또는 최신 상세가 현재 filter에서 처리 불가일 때만 다른 검수자의
      // 선처리로 확정한다. page 부재만으로는 pagination 이동과 구분할 수 없다.
      if (!isCurrentWorkflow || workflow.visibleIndex < 0) {
        // page 밖이거나 A→B→A로 workflow epoch가 바뀌었다면 과거 순서 anchor를
        // 재사용하지 않고 A만 비운다. 초기 선택 effect가 최신 큐의 첫 후보로 복귀한다.
        clearProcessedCandidateParam(candidateId, false);
        cancelCategoryMatch();
        initialSelectionDoneRef.current = false;
        selectedCandidateIdRef.current = null;
        setQueueCompleted(false);
        removeCandidateSelections([candidateId]);
        setSelectedCandidateSnapshot(null);
        setSelectedId(null);
        return true;
      }
      advanceAfterProcessing(
        candidateId,
        [candidateId],
        workflow.visibleIndex,
        workflow.orderedCandidateIds,
        workflow.loadedPageCount,
      );
      return true;
    },
    [
      advanceAfterProcessing,
      cancelCategoryMatch,
      clearProcessedCandidateParam,
      queryClient,
      queueScopeRef,
      removeCandidateSelections,
      reviewListStateRef,
      selectedCandidateIdRef,
      selectionScopeEpochRef,
      setSelectedCandidateSnapshot,
      initialSelectionDoneRef,
      setQueueCompleted,
      setSelectedId,
    ],
  );
  return { reconcileFailedCandidateSelection };
}

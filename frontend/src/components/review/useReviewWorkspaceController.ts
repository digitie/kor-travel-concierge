"use client";

import { useCandidateSearch } from "@/components/review/useCandidateSearch";
import { useReviewKeyboard } from "@/components/review/useReviewKeyboard";
import { useReviewQueue } from "@/components/review/useReviewQueue";
import type { UnmatchedCandidate } from "@/lib/api";
import { listCategories } from "@/lib/api";
import { candidateReviewStateLabel } from "@/lib/display-labels";
import {
  isCurrentReviewWorkflow,
  isReviewCandidateActionable,
  parseReviewCandidateId,
  parseReviewListState,
  writeReviewListState,
  type ReviewListState,
} from "@/lib/review-list-state";
import { useIsMobile } from "@/lib/use-is-mobile";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useStore } from "zustand";
import { createReviewUiStore } from "./review-ui-store";

import type {
  NearbyConflict,
  PendingCandidateAdvance,
  ResolveCommand,
  ResolveCommandDraft,
} from "./review-workspace-model";
import {
  buildHintedQuery,
  candidateCategoryForm,
  reviewCandidateActionStatus,
  reviewCoordinateValidation,
  reviewDetailActionState,
  reviewQueueLoadStatus,
  reviewTriageProgress,
} from "./review-workspace-model";
import { useCandidateDeleteWorkflow } from "./useCandidateDeleteWorkflow";
import {
  useCandidateReopening,
  useCandidateReopenRequest,
} from "./useCandidateReopening";
import { useCandidateResolution } from "./useCandidateResolution";
import { useReviewBulkActions } from "./useReviewBulkActions";
import {
  useFailedCandidateSelection,
  useReviewCandidateAdvance,
  useReviewCandidatePicker,
} from "./useReviewCandidatePicker";
import {
  useReviewMapPlaces,
  useReviewPlaceSelection,
} from "./useReviewPlaceSelection";
import { useReviewReprocessing } from "./useReviewReprocessing";
import {
  useAuthoritativeCandidate,
  useCandidateDetailState,
  useCandidateEditorState,
  useReviewQueueSelection,
  useReviewSelectionSession,
} from "./useReviewSelectionSession";
import { useReviewCacheStatus, useReviewUndoState } from "./useReviewUndoState";

export function useReviewWorkspaceController() {
  const [ui] = useState(() =>
    createReviewUiStore<PendingCandidateAdvance, NearbyConflict>(),
  );
  const queryClient = useQueryClient();
  const router = useRouter();
  const {
    candidates,
    candidatePages,
    candidatePaginationContractError,
    candidatesKey,
    candidatesKeyRef,
    candidatesQuery,
    candidateTotal,
    canLoadMoreCandidates,
    commitReviewUrl,
    facetsQuery,
    groundingStatus,
    groupDim,
    groupValue,
    hasListUrlState,
    hasReviewFilters,
    isDomestic,
    isRemovedView,
    newCandidateNotice,
    newCandidatesQuery,
    queueReason,
    queueScope,
    queueScopeRef,
    reviewListState,
    reviewListStateRef,
    reviewMode,
    reviewQuery,
    reviewSearchParams,
    reviewSort,
    reviewStatus,
    setReviewMode,
    sourceKind,
    updateReviewListState,
    updateReviewQuery,
  } = useReviewQueue();
  // 카테고리 강제 드롭다운 목록(정적 카탈로그 — 오래 캐시).
  const categoriesQuery = useQuery({
    queryKey: ["categories"],
    queryFn: listCategories,
    staleTime: 60 * 60 * 1000,
  });
  // 장바구니: 선택한 영상 id를 sessionStorage에 보존 → 그룹 필터를 바꿔도(테이블 필터링)
  // 선택이 유지된다(쇼핑몰 장바구니). 영상 단위로 dedup.
  const {
    cart,
    setCart,
    reprocessStage,
    setReprocessStage,
    cartSet,
    toggleCart,
    reprocessMutation,
  } = useReviewReprocessing({ queryClient });
  const previousQueueScopeRef = useRef(queueScope);
  const {
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
  } = useReviewQueueSelection({
    ui,
    candidates,
    reviewSearchParams,
    isRemovedView,
  });
  const {
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
  } = useReviewSelectionSession(ui);
  const {
    reviewUndoState,
    reviewUndoStateRef,
    reviewUndoError,
    setReviewUndoError,
    updateReviewUndoState,
  } = useReviewUndoState();
  const {
    candidateCacheRefreshError,
    candidateCacheRefreshGenerationRef,
    markCandidateCacheRefreshError,
    clearCandidateCacheRefreshError,
  } = useReviewCacheStatus();

  // URL 후보가 바뀌면 필터는 보존하고 단건 상세 조회가 끝날 때까지 기존 snapshot을 비운다.

  useLayoutEffect(() => {
    return ui.batch(() => {
      if (previousDeepLinkIdRef.current === deepLinkedCandidateId) return;
      previousDeepLinkIdRef.current = deepLinkedCandidateId;
      invalidateCandidateWorkflow();
      ui.actions.setDeepLinkNotFound(null);
      if (deepLinkedCandidateId == null) {
        if (preserveSelectionOnDeepLinkClearRef.current) {
          preserveSelectionOnDeepLinkClearRef.current = false;
          initialSelectionDoneRef.current = true;
          return;
        }
        initialSelectionDoneRef.current = false;
        ui.actions.setSelectedCandidateSnapshot(null);
        ui.actions.setSelectedId(null);
        return;
      }
      preserveSelectionOnDeepLinkClearRef.current = false;
      initialSelectionDoneRef.current = false;
      ui.actions.setSelectedCandidateSnapshot(null);
      ui.actions.setSelectedId(deepLinkedCandidateId);
    });
  }, [
    deepLinkedCandidateId,
    initialSelectionDoneRef,
    invalidateCandidateWorkflow,
    preserveSelectionOnDeepLinkClearRef,
    previousDeepLinkIdRef,
    ui,
  ]);

  const {
    selected,
    recoveryDetailQuery,
    authoritativeRecoveryCandidate,
    deepLinkStatusOut,
    deepLinkFilterOut,
    deepLinkLoadedOut,
    selectedActionable,
  } = useAuthoritativeCandidate({
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
  });
  const queryEdit = useStore(ui.store, (state) => state.queryEdit);
  const setQueryEdit = ui.actions.setQueryEdit;
  const query = queryEdit ?? (selected ? buildHintedQuery(selected) : "");
  const externalResolutionEnabled = !isRemovedView && selectedActionable;
  const {
    activeQuery,
    searchQuery,
    result,
    allHits,
    opinionHits,
    opinionRequested,
    opinionQuery,
    opinionResult,
    gemini,
    prepareCandidate,
    runSearch: runCandidateSearch,
    stopSearch,
    requestOpinion,
  } = useCandidateSearch({ enabled: externalResolutionEnabled });

  // 검색 결과가 도착하면(검색 버튼/후보 선택 자동검색 모두) 결과 영역을 화면에 보이도록
  // 스크롤한다. 확정 정보 폼(#3)이 위에 있어 검색 결과가 폴드 아래로 밀리던 문제 해결.
  const resultsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (result) {
      resultsRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
  }, [result]);

  const isMobile = useIsMobile();
  // 단축키 `/` 포커스 대상과 `?` 도움말 오버레이 상태(T-187).
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false);
  const {
    detailId,
    detailIdRef,
    detailGenerationRef,
    setDetailId,
    detailDeletePending,
    setDetailDeletePending,
    detailDeleteSnapshotRef,
  } = useCandidateDetailState();
  // 행 단위 삭제 확인: 2,000행에 AlertDialog를 하나씩 두면 렌더 비용이 폭증하므로
  // 페이지에 공용 다이얼로그 하나만 두고 대상 후보를 상태로 넘긴다.
  const [deleteTarget, setDeleteTarget] = useState<UnmatchedCandidate | null>(
    null,
  );
  const deleteTargetScopeRef = useRef<string | null>(null);
  const requestCandidateDelete = useCallback(
    (candidate: UnmatchedCandidate) => {
      deleteTargetScopeRef.current = queueScopeRef.current;
      setDeleteTarget(candidate);
    },
    [queueScopeRef],
  );

  const {
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
  } = useCandidateEditorState({ ui, selected });

  useLayoutEffect(() => {
    return ui.batch(() => {
      if (previousQueueScopeRef.current === queueScope) return;
      previousQueueScopeRef.current = queueScope;
      invalidateCandidateWorkflow();
      initialSelectionDoneRef.current = false;
      updatePendingCandidateAdvance(null);
      selectedCandidateIdRef.current = null;
      if (!detailDeletePending) detailDeleteSnapshotRef.current = null;
      deleteTargetScopeRef.current = null;
      ui.actions.setQueueCompleted(false);
      ui.actions.setSelectedCandidateIds([]);
      ui.actions.setSelectedCandidateSnapshot(null);
      ui.actions.setSelectedId(null);
      ui.actions.setNearbyConflict(null);
      setDeleteTarget(null);
      setDetailId(null);
      ui.actions.setCandidateActionError(null);
      clearCandidateCacheRefreshError();
    });
  }, [
    clearCandidateCacheRefreshError,
    detailDeletePending,
    detailDeleteSnapshotRef,
    initialSelectionDoneRef,
    invalidateCandidateWorkflow,
    queueScope,
    selectedCandidateIdRef,
    setDetailId,
    ui,
    updatePendingCandidateAdvance,
  ]);

  const cancelCategoryMatch = useCallback(() => {
    categoryMatchRequestRef.current += 1;
    categoryMatchAbortRef.current?.abort();
    categoryMatchAbortRef.current = null;
  }, [categoryMatchAbortRef, categoryMatchRequestRef]);


  useEffect(() => {
    return ui.batch(() => {
      if (externalResolutionEnabled) return;
      cancelCategoryMatch();
      ui.actions.setQueryEdit(null);
      ui.actions.setSelectedHit(null);
    });
  }, [cancelCategoryMatch, externalResolutionEnabled, ui]);


  useEffect(
    () => () => {
      cancelCategoryMatch();
    },
    [cancelCategoryMatch],
  );
  useEffect(() => {
    if (selected?.id != null) {
      selectedCandidateIdRef.current = selected.id;
    } else if (selectedId == null) {
      selectedCandidateIdRef.current = null;
    }
  }, [selected?.id, selectedCandidateIdRef, selectedId]);


  useEffect(() => {
    return ui.batch(() => {
      const candidateId = selected?.id ?? null;
      if (candidateId === formCandidateId) return;
      cancelCategoryMatch();
      ui.actions.setQueryEdit(null);
      ui.actions.setFormCandidateId(candidateId);
      ui.actions.setSelectedHit(null);
      ui.actions.setNearbyConflict(null);
      ui.actions.setCategoryEdited(false);
      ui.actions.setForm(
        selected
          ? {
              name: "",
              latitude: "",
              longitude: "",
              ...candidateCategoryForm(selected),
            }
          : {
              name: "",
              latitude: "",
              longitude: "",
              category: "",
              categoryCode: "",
            },
      );
      prepareCandidate(
        selected
          ? {
              candidateId: selected.id,
              requestIdentity: `${queueScopeRef.current}:${selectionScopeEpochRef.current}:${selected.state_revision}`,
              query: buildHintedQuery(selected),
            }
          : null,
        { autoSearch: false, providerEnabled: false },
      );
    });
  }, [
    cancelCategoryMatch,
    formCandidateId,
    prepareCandidate,
    queueScopeRef,
    selected,
    selectionScopeEpochRef,
    ui,
  ]);


  function runSearch() {
    if (!externalResolutionEnabled || !selected || !query.trim()) return;
    runCandidateSearch({
      candidateId: selected.id,
      requestIdentity: `${queueScopeRef.current}:${selectionScopeEpochRef.current}:${selected.state_revision}`,
      query,
    });
  }
  // 검수 상세: 모바일=새 페이지, PC=모달.
  const openDetail = useCallback(
    (candidateId: number) => {
      if (isMobile) {
        router.push(`/review/${candidateId}`);
      } else {
        detailDeleteSnapshotRef.current = null;
        setDetailId(candidateId);
      }
    },
    [detailDeleteSnapshotRef, isMobile, router, setDetailId],
  );
  const clearCandidateParam = useCallback(
    (preserveSelection = false) => {
      invalidateCandidateWorkflow();
      const url = new URL(window.location.href);
      const hadCandidateParam = url.searchParams.has("candidate");
      if (hadCandidateParam) {
        preserveSelectionOnDeepLinkClearRef.current = preserveSelection;
        url.searchParams.delete("candidate");
        commitReviewUrl(url.searchParams);
      }
      initialSelectionDoneRef.current = preserveSelection || hadCandidateParam;
      if (preserveSelection) return;
      selectedCandidateIdRef.current = null;
      setDeepLinkNotFound(null);
      setSelectedCandidateIds([]);
      setSelectedCandidateSnapshot(null);
      setSelectedId(null);
    },
    [
      commitReviewUrl,
      initialSelectionDoneRef,
      invalidateCandidateWorkflow,
      preserveSelectionOnDeepLinkClearRef,
      selectedCandidateIdRef,
      setDeepLinkNotFound,
      setSelectedCandidateIds,
      setSelectedCandidateSnapshot,
      setSelectedId,
    ],
  );
  const clearProcessedCandidateParam = useCallback(
    (candidateId: number, preserveSelection = true) => {
      const url = new URL(window.location.href);
      if (parseReviewCandidateId(url.searchParams) !== candidateId)
        return false;
      invalidateCandidateWorkflow();
      preserveSelectionOnDeepLinkClearRef.current = preserveSelection;
      url.searchParams.delete("candidate");
      setDeepLinkNotFound(null);
      commitReviewUrl(url.searchParams);
      return true;
    },
    [
      commitReviewUrl,
      invalidateCandidateWorkflow,
      preserveSelectionOnDeepLinkClearRef,
      setDeepLinkNotFound,
    ],
  );
  const { pickCandidate } = useReviewCandidatePicker({
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
  });

  // J/K 단축키: 현재 표시된 후보 목록에서 상대 이동. 수동 목록 클릭과 동일하게
  // pickCandidate(자동 검색·딥링크 해제)를 쓴다(T-187).
  const pickCandidateOffset = useCallback(
    (offset: number) => {
      if (candidates.length === 0) return;
      const currentId = selectedCandidateIdRef.current;
      const currentIndex =
        currentId == null
          ? -1
          : candidates.findIndex((candidate) => candidate.id === currentId);
      const nextIndex =
        currentIndex < 0
          ? offset > 0
            ? 0
            : candidates.length - 1
          : currentIndex + offset;
      if (nextIndex < 0 || nextIndex >= candidates.length) return;
      pickCandidate(candidates[nextIndex]);
    },
    [candidates, pickCandidate, selectedCandidateIdRef],
  );

  const { continueCandidateAdvance } = useReviewCandidateAdvance({
    candidates,
    updatePendingCandidateAdvance,
    setQueueCompleted,
    pickCandidate,
    candidatePages,
    candidatePaginationContractError,
    candidatesQuery,
    setSelectedCandidateSnapshot,
    setSelectedId,
  });

  const advanceAfterProcessing = useCallback(
    (
      processedId: number,
      processedIds: number[] = [processedId],
      visibleIndex?: number,
      orderedCandidateIds: number[] = candidates.map(
        (candidate) => candidate.id,
      ),
      loadedPageCount: number = candidatePages.length,
    ) => {
      const anchorIndex =
        visibleIndex ??
        orderedCandidateIds.findIndex(
          (candidateId) => candidateId === processedId,
        );
      // 처리 완료가 확인된 후보의 checkbox 선택도 같은 경로에서 제거한다. 목록에서
      // 잠시 사라진 ID를 state에 남기면 reopen 뒤 과거 bulk 선택이 되살아날 수 있다.
      removeCandidateSelections(processedIds);
      if (anchorIndex < 0) return;
      clearProcessedCandidateParam(processedId);
      continueCandidateAdvance({
        processedIds,
        anchorIndex,
        orderedCandidateIds,
        loadedPageCount,
      });
    },
    [
      candidatePages.length,
      candidates,
      clearProcessedCandidateParam,
      continueCandidateAdvance,
      removeCandidateSelections,
    ],
  );

  const { reconcileFailedCandidateSelection } = useFailedCandidateSelection({
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
  });

  useEffect(() => {
    const pending = pendingCandidateAdvance;
    if (!pending || candidatesQuery.isFetchingNextPage) return;
    continueCandidateAdvance(pending);
  }, [
    candidatesQuery.isFetchingNextPage,
    candidatesQuery.data,
    continueCandidateAdvance,
    pendingCandidateAdvance,
  ]);

  useEffect(() => {
    return ui.batch(() => {
      // URL 상태를 아직 확정하지 않은 disabled query를 빈 큐로 오인하면, 느린 첫 응답에서는
      // initialSelectionDoneRef가 먼저 잠겨 첫 후보 자동 선택이 영구히 건너뛰어진다.
      if (
        !hasListUrlState ||
        initialSelectionDoneRef.current ||
        pendingCandidateAdvance
      ) {
        return;
      }
      const deepLinkedId = deepLinkedCandidateId;
      if (deepLinkedId != null) {
        if (deepLinkDetailQuery.isFetching) return;
        const linked = deepLinkDetailQuery.data?.list_item;
        if (!linked || linked.id !== deepLinkedId) {
          ui.actions.setDeepLinkNotFound(
            deepLinkDetailQuery.error?.message ??
              `검수 후보 #${deepLinkedId}을(를) 찾을 수 없습니다.`,
          );
          initialSelectionDoneRef.current = true;
          return;
        }
        ui.actions.setDeepLinkNotFound(null);
        initialSelectionDoneRef.current = true;
        pickCandidate(linked, { autoSearch: false, preserveWorkflow: true });
        return;
      }
      if (candidatesQuery.isFetching) return;
      if (selectedId != null) return;
      const first = candidates[0];
      if (first) {
        initialSelectionDoneRef.current = true;
        pickCandidate(first, { autoSearch: false, preserveWorkflow: true });
        return;
      }
      if (
        candidatesQuery.hasNextPage &&
        !candidatesQuery.isFetchNextPageError &&
        !candidatePaginationContractError
      ) {
        void candidatesQuery.fetchNextPage({ cancelRefetch: false });
        return;
      }
      if (!candidatesQuery.isError && !candidatePaginationContractError) {
        initialSelectionDoneRef.current = true;
      }
    });
  }, [
    candidates,
    candidatePaginationContractError,
    candidatesQuery,
    deepLinkedCandidateId,
    deepLinkDetailQuery.data,
    deepLinkDetailQuery.error,
    deepLinkDetailQuery.isFetching,
    hasListUrlState,
    pendingCandidateAdvance,
    pickCandidate,
    selectedId,
    ui,
    initialSelectionDoneRef,
  ]);

  useEffect(() => {
    if (
      !queueCompleted ||
      candidatesQuery.isFetching ||
      pendingCandidateAdvance ||
      candidates.length === 0
    ) {
      return;
    }
    initialSelectionDoneRef.current = true;
    pickCandidate(candidates[0], {
      autoSearch: false,
      preserveWorkflow: true,
    });
  }, [
    candidatesQuery.isFetching,
    candidates,
    pendingCandidateAdvance,
    pickCandidate,
    queueCompleted,
    initialSelectionDoneRef,
  ]);

  const { deleteCandidatesMutation } = useCandidateDeleteWorkflow({
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
  });

  const { selectHit, applyGemini } = useReviewPlaceSelection({
    selected,
    cancelCategoryMatch,
    result,
    activeQuery,
    setSelectedHit,
    setNearbyConflict,
    setFormCandidateId,
    setForm,
    categoryEdited,
    categoryMatchAbortRef,
    categoryMatchRequestRef,
    selectedCandidateIdRef,
  });

  const activeSelectedHit =
    selectedHit?.candidateId === selected?.id ? selectedHit : null;
  // 선택 가능 hit(저장 허용 + 좌표 존재)만 렌더 순서대로 모은 단일 정본. 키보드 1–9,
  // 행 번호 배지, 지도 번호가 모두 이 배열의 같은 index+1을 쓴다(T-187 정합).
  const { selectableHits, mapHitEntries, mapPlaces } = useReviewMapPlaces({
    allHits,
    externalResolutionEnabled,
    form,
    activeSelectedHit,
  });

  function isCurrentResolveCommand(command: ResolveCommandDraft): boolean {
    return isCurrentReviewWorkflow({
      commandCandidateId: command.candidateId,
      commandQueueScope: command.queueScope,
      commandEpoch: command.workflowEpoch,
      currentCandidateId: selectedCandidateIdRef.current,
      currentQueueScope: queueScopeRef.current,
      currentEpoch: selectionScopeEpochRef.current,
    });
  }

  const { resolveMutation } = useCandidateResolution({
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
  });

  function submitResolveCommand(command: ResolveCommandDraft) {
    if (deepLinkValidationPending || resolveMutation.isPending) return;
    if (!isCurrentResolveCommand(command)) {
      setNearbyConflict(null);
      setCandidateActionError(
        `${command.candidateName} 후보는 현재 선택 또는 표시 조건과 달라 처리하지 않았습니다. 현재 후보에서 다시 시도해 주세요.`,
      );
      return;
    }
    const attempt = () =>
      resolveMutation.mutate({
        ...command,
        clientOperationId: crypto.randomUUID(),
      });
    if (deepLinkedCandidateId !== command.candidateId) {
      attempt();
      return;
    }

    // page 밖 단건은 제출 직전에 다시 읽어, 다른 검수자가 먼저 처리한 후보를
    // 오래된 폼으로 재확정하지 않는다.
    const validationGeneration = validationGenerationRef.current + 1;
    validationGenerationRef.current = validationGeneration;
    setDeepLinkValidationPending(true);
    void deepLinkDetailQuery
      .refetch()
      .then(({ data, error }) => {
        if (
          validationGenerationRef.current !== validationGeneration ||
          !isCurrentResolveCommand(command)
        ) {
          return;
        }
        if (error) {
          setCandidateActionError(
            `후보의 최신 상태를 확인하지 못해 처리하지 않았습니다: ${error.message}`,
          );
          return;
        }
        const latest = data?.list_item;
        if (!latest || latest.id !== command.candidateId) {
          setCandidateActionError("후보의 최신 상태를 확인하지 못했습니다.");
          return;
        }
        setSelectedCandidateSnapshot(latest);
        if (!isReviewCandidateActionable(latest)) {
          setCandidateActionError(
            `후보 상태가 ${candidateReviewStateLabel(latest.review_state)}(으)로 변경되어 처리하지 않았습니다.`,
          );
          return;
        }
        attempt();
      })
      .finally(() => {
        if (validationGenerationRef.current === validationGeneration) {
          setDeepLinkValidationPending(false);
        }
      });
  }

  function resolveSelected(
    action: "create_place" | "ignore",
    duplicate?: ResolveCommand["duplicate"],
  ) {
    if (!selected || formCandidateId !== selected.id || !selectedActionable) {
      return;
    }
    setCandidateActionError(null);
    submitResolveCommand({
      candidateId: selected.id,
      expectedRevision: selected.state_revision,
      candidateName: selected.ai_place_name,
      visibleIndex: candidates.findIndex(
        (candidate) => candidate.id === selected.id,
      ),
      orderedCandidateIds: candidates.map((candidate) => candidate.id),
      loadedPageCount: candidatePages.length,
      queueScope,
      workflowEpoch: selectionScopeEpochRef.current,
      candidatesKey,
      action,
      form: { ...form },
      selectedHit: activeSelectedHit,
      duplicate,
    });
  }

  const navigateToReopenedCandidate = useCallback(
    (candidate: UnmatchedCandidate) => {
      const current = new URL(window.location.href);
      const nextState: ReviewListState = {
        ...parseReviewListState(current.searchParams),
        status: "needs_review",
      };
      const params = writeReviewListState(current.searchParams, nextState);
      params.set("candidate", String(candidate.id));
      initialSelectionDoneRef.current = false;
      setDeepLinkNotFound(null);
      commitReviewUrl(params);
    },
    [commitReviewUrl, initialSelectionDoneRef, setDeepLinkNotFound],
  );

  const { reopenMutation } = useCandidateReopening({
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
  });

  const { requestCandidateReopen } = useCandidateReopenRequest({
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
  });
  const restoreCandidateFromRemovedList = useCallback(
    (candidate: UnmatchedCandidate) =>
      requestCandidateReopen(candidate, "removed_list"),
    [requestCandidateReopen],
  );

  const resetReviewScope = useCallback(() => {
    initialSelectionDoneRef.current = false;
    updatePendingCandidateAdvance(null);
    selectedCandidateIdRef.current = null;
    cancelCategoryMatch();
    clearCandidateParam();
    setQueueCompleted(false);
    setSelectedCandidateSnapshot(null);
    setSelectedId(null);
  }, [
    cancelCategoryMatch,
    clearCandidateParam,
    initialSelectionDoneRef,
    selectedCandidateIdRef,
    setQueueCompleted,
    setSelectedCandidateSnapshot,
    setSelectedId,
    updatePendingCandidateAdvance,
  ]);

  const restartCandidateSnapshot = useCallback(async () => {
    const restartScope = queueScopeRef.current;
    const restartCandidatesKey = candidatesKeyRef.current;
    const cacheRefreshGeneration = candidateCacheRefreshGenerationRef.current;
    resetReviewScope();
    await queryClient.cancelQueries({
      queryKey: restartCandidatesKey,
      exact: true,
    });
    // resetQueries가 infinite query의 pages/pageParams를 함께 폐기해 첫 page부터
    // 새 watermark snapshot을 만든다.
    await queryClient.resetQueries({
      queryKey: restartCandidatesKey,
      exact: true,
    });
    await queryClient.invalidateQueries({
      queryKey: ["unmatched-candidates", "newer"],
    });
    if (
      queueScopeRef.current === restartScope &&
      candidateCacheRefreshGenerationRef.current === cacheRefreshGeneration &&
      queryClient.getQueryState(restartCandidatesKey)?.status !== "error"
    ) {
      clearCandidateCacheRefreshError();
    }
  }, [
    candidateCacheRefreshGenerationRef,
    candidatesKeyRef,
    clearCandidateCacheRefreshError,
    queryClient,
    queueScopeRef,
    resetReviewScope,
  ]);

  const {
    reviewBulkDialogOpen,
    bulkDialogState,
    bulkBlocksCandidateActions,
    updateReviewBulkDialogOpen,
    beginReviewBulk,
    startConfirmedReviewBulk,
    retryVisibleReviewBulk,
    abandonVisibleReviewBulk,
  } = useReviewBulkActions({
    setSelectedCandidateIds,
    updateReviewUndoState,
    setReviewUndoError,
    queryClient,
    restartCandidateSnapshot,
    queueScope,
    setCandidateActionError,
    selectedBulkCandidateIds,
    reviewListStateRef,
  });

  // 좌표 입력 검증: 숫자 여부(차단) + 대한민국 대략 범위(경고만, 저장은 허용).
  const { latInvalid, lngInvalid, coordsOutOfKorea, canSave } =
    reviewCoordinateValidation({
      form,
      selected,
      selectedActionable,
      formCandidateId,
      activeSelectedHit,
    });
  const {
    candidateAdvancePending,
    candidateAdvanceError,
    candidateLoadError,
    candidateSnapshotRefetchError,
    candidateAppendError,
  } = reviewQueueLoadStatus({
    pendingCandidateAdvance,
    candidatePaginationContractError,
    candidatesQuery,
    deepLinkNotFound,
    deepLinkedCandidateId,
    deepLinkDetailQuery,
    candidates,
    candidateCacheRefreshError,
  });
  const { candidateActionPending } = reviewCandidateActionStatus({
    resolveMutation,
    deleteCandidatesMutation,
    reopenMutation,
    detailDeletePending,
    deepLinkValidationPending,
    bulkBlocksCandidateActions,
  });

  // 처리 단축키(T-187). 개별 액션은 각자의 가드(canSave·selectedActionable·undo
  // 존재)를 다시 확인해, 전역 keydown 가드를 통과해도 부적합 상태에서는 무해하다.
  useReviewKeyboard({
    enabled: hasListUrlState,
    onNextCandidate: () => pickCandidateOffset(1),
    onPrevCandidate: () => pickCandidateOffset(-1),
    onSelectHit: (ordinal) => {
      const hit = selectableHits[ordinal - 1];
      if (hit) selectHit(hit);
    },
    onSave: () => {
      if (canSave && !candidateActionPending) resolveSelected("create_place");
    },
    onExclude: () => {
      if (selected && selectedActionable && !candidateActionPending) {
        requestCandidateDelete(selected);
      }
    },
    onUndo: () => {
      const entry = reviewUndoStateRef.current.current;
      if (!entry || candidateActionPending) return;
      requestCandidateReopen(
        {
          id: entry.descriptor.candidate_id,
          ai_place_name: entry.candidateName,
          review_state: entry.expectedReviewState,
          undo: entry.descriptor,
        },
        "snackbar",
      );
    },
    onFocusSearch: () => searchInputRef.current?.focus(),
    onToggleHelp: () => setShortcutHelpOpen((open) => !open),
  });

  const { candidateInitialLoading, detailCandidate, deleteTargetActionable } =
    reviewDetailActionState({
      hasListUrlState,
      candidates,
      candidatesQuery,
      deepLinkedCandidateId,
      deepLinkDetailQuery,
      detailId,
      deepLinkItem,
      deleteTarget,
    });

  function retryCandidateAdvance() {
    if (candidatePaginationContractError) {
      void restartCandidateSnapshot();
      return;
    }
    if (
      !pendingCandidateAdvance ||
      !candidatesQuery.hasNextPage ||
      candidatesQuery.isFetchingNextPage
    ) {
      return;
    }
    void candidatesQuery.fetchNextPage({ cancelRefetch: false });
  }

  function retryCandidateLoad() {
    setDeepLinkNotFound(null);
    initialSelectionDoneRef.current = false;
    if (deepLinkedCandidateId != null) {
      void deepLinkDetailQuery.refetch();
      return;
    }
    if (
      candidatesQuery.isFetchNextPageError &&
      candidatesQuery.hasNextPage &&
      !candidatesQuery.isFetchingNextPage
    ) {
      void candidatesQuery.fetchNextPage({ cancelRefetch: false });
      return;
    }
    void restartCandidateSnapshot();
  }

  // 처리 모드(triage) 진행 지표: n/m은 T-182 filtered total 기준, 남은 수는 현재
  // 위치 이후 후보 수의 근사다(스냅숏 total - 현재 위치).
  const isTriage = reviewMode === "triage";
  const { triagePosition, triageRemaining, lastProcessed } =
    reviewTriageProgress({
      selected,
      candidates,
      candidateTotal,
      reviewUndoState,
    });

  return {
    setShortcutHelpOpen,
    candidates,
    candidateTotal,
    isTriage,
    candidatesQuery,
    restartCandidateSnapshot,
    facetsQuery,
    triagePosition,
    queueCompleted,
    triageRemaining,
    lastProcessed,
    candidateActionPending,
    reviewUndoStateRef,
    requestCandidateReopen,
    reviewUndoError,
    isRemovedView,
    reviewQuery,
    updateReviewQuery,
    reviewStatus,
    updateReviewListState,
    groupDim,
    groupValue,
    reviewSort,
    isDomestic,
    queueReason,
    sourceKind,
    groundingStatus,
    hasReviewFilters,
    newCandidatesQuery,
    newCandidateNotice,
    candidateAppendError,
    candidateCacheRefreshError,
    candidatePaginationContractError,
    candidateSnapshotRefetchError,
    retryCandidateLoad,
    deleteCandidatesMutation,
    candidateActionError,
    reprocessMutation,
    cart,
    reprocessStage,
    setReprocessStage,
    setCart,
    candidateAdvancePending,
    candidateAdvanceError,
    retryCandidateAdvance,
    candidateInitialLoading,
    candidateLoadError,
    deepLinkedCandidateId,
    selected,
    selectedCandidateSet,
    cartSet,
    bulkSelectableLoadedCandidateIds,
    allLoadedCandidatesSelected,
    someLoadedCandidatesSelected,
    bulkSelectionLimitReached,
    deepLinkItem,
    toggleAllLoadedCandidates,
    toggleCandidateSelection,
    pickCandidate,
    toggleCart,
    openDetail,
    requestCandidateDelete,
    restoreCandidateFromRemovedList,
    canLoadMoreCandidates,
    selectedBulkCandidateIds,
    hasListUrlState,
    bulkDialogState,
    reviewBulkDialogOpen,
    setSelectedCandidateIds,
    beginReviewBulk,
    startConfirmedReviewBulk,
    retryVisibleReviewBulk,
    abandonVisibleReviewBulk,
    updateReviewBulkDialogOpen,
    deepLinkDetailQuery,
    deepLinkStatusOut,
    deepLinkFilterOut,
    deepLinkLoadedOut,
    authoritativeRecoveryCandidate,
    recoveryDetailQuery,
    reopenMutation,
    selectedActionable,
    searchInputRef,
    query,
    setQueryEdit,
    runSearch,
    searchQuery,
    stopSearch,
    form,
    activeSelectedHit,
    categoriesQuery,
    latInvalid,
    lngInvalid,
    coordsOutOfKorea,
    canSave,
    resolveMutation,
    queueScope,
    nearbyConflict,
    setForm,
    cancelCategoryMatch,
    setCategoryEdited,
    resolveSelected,
    setNearbyConflict,
    submitResolveCommand,
    resultsRef,
    activeQuery,
    result,
    opinionHits,
    selectableHits,
    opinionRequested,
    gemini,
    opinionQuery,
    opinionResult,
    requestOpinion,
    applyGemini,
    selectHit,
    externalResolutionEnabled,
    mapPlaces,
    mapHitEntries,
    detailId,
    detailDeletePending,
    setDetailId,
    setDetailDeletePending,
    detailDeleteSnapshotRef,
    candidatePages,
    selectionScopeEpochRef,
    candidatesKey,
    detailCandidate,
    updateReviewUndoState,
    setCandidateActionError,
    setReviewUndoError,
    reviewListStateRef,
    removeCandidateSelections,
    reconcileFailedCandidateSelection,
    candidatesKeyRef,
    queueScopeRef,
    markCandidateCacheRefreshError,
    queryClient,
    selectedCandidateIdRef,
    advanceAfterProcessing,
    clearProcessedCandidateParam,
    initialSelectionDoneRef,
    setQueueCompleted,
    setSelectedCandidateSnapshot,
    setSelectedId,
    deleteTarget,
    deleteTargetScopeRef,
    setDeleteTarget,
    deleteTargetActionable,
    reviewUndoState,
    shortcutHelpOpen,
    reviewMode,
    setReviewMode,
  };
}

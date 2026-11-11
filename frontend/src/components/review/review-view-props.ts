"use client";

import type { useReviewWorkspaceController } from "./useReviewWorkspaceController";

export type ReviewWorkspaceModel = ReturnType<
  typeof useReviewWorkspaceController
>;

/** 표시 조각에 필요한 값만 전달해 관련 없는 model 값에 결합하지 않는다. */
function reviewViewProps<T extends object, K extends keyof T>(
  model: T,
  keys: readonly K[],
): Pick<T, K> {
  const values = {} as Pick<T, K>;
  for (const key of keys) values[key] = model[key];
  return values;
}

export function reviewEmptySelectionStatus({
  candidateAdvancePending,
  candidateInitialLoading,
  candidateLoadError,
  queueCompleted,
  candidateAdvanceError,
  isRemovedView,
}: Pick<
  ReviewWorkspaceModel,
  | "candidateAdvancePending"
  | "candidateInitialLoading"
  | "candidateLoadError"
  | "queueCompleted"
  | "candidateAdvanceError"
  | "isRemovedView"
>) {
  const role: "status" | "alert" | undefined =
    candidateAdvancePending || candidateInitialLoading
      ? "status"
      : candidateLoadError
        ? "alert"
        : queueCompleted
          ? "status"
          : undefined;
  const message = candidateAdvancePending
    ? (candidateAdvanceError ?? "다음 검수 후보를 불러오는 중…")
    : candidateInitialLoading
      ? "검수 후보를 불러오는 중…"
      : candidateLoadError
        ? candidateLoadError
        : queueCompleted
          ? isRemovedView
            ? "현재 표시 조건에 복구할 후보가 없습니다."
            : "현재 표시 조건의 검수 후보를 모두 처리했습니다."
          : isRemovedView
            ? "제외·삭제된 후보가 없습니다."
            : "검수할 후보가 없습니다.";
  return { role, message };
}

const triageProgressPanelKeys = [
  "candidatesQuery",
  "restartCandidateSnapshot",
  "facetsQuery",
  "triagePosition",
  "candidateTotal",
  "queueCompleted",
  "triageRemaining",
  "lastProcessed",
  "candidateActionPending",
  "reviewUndoStateRef",
  "requestCandidateReopen",
  "reviewUndoError",
] as const;

export function triageProgressPanelProps(
  model: Pick<ReviewWorkspaceModel, (typeof triageProgressPanelKeys)[number]>,
) {
  return reviewViewProps(model, triageProgressPanelKeys);
}

const reviewQueueSidebarKeys = [
  "isRemovedView",
  "candidatesQuery",
  "restartCandidateSnapshot",
  "facetsQuery",
  "candidates",
  "candidateTotal",
  "reviewQuery",
  "updateReviewQuery",
  "reviewStatus",
  "updateReviewListState",
  "groupDim",
  "groupValue",
  "reviewSort",
  "isDomestic",
  "queueReason",
  "sourceKind",
  "groundingStatus",
  "hasReviewFilters",
  "newCandidatesQuery",
  "newCandidateNotice",
  "candidateAppendError",
  "candidateCacheRefreshError",
  "candidatePaginationContractError",
  "candidateSnapshotRefetchError",
  "retryCandidateLoad",
  "deleteCandidatesMutation",
  "candidateActionError",
  "reprocessMutation",
  "cart",
  "reprocessStage",
  "setReprocessStage",
  "setCart",
  "candidateAdvancePending",
  "candidateAdvanceError",
  "retryCandidateAdvance",
  "candidateInitialLoading",
  "candidateLoadError",
  "deepLinkedCandidateId",
  "queueCompleted",
  "selected",
  "selectedCandidateSet",
  "cartSet",
  "bulkSelectableLoadedCandidateIds",
  "allLoadedCandidatesSelected",
  "someLoadedCandidatesSelected",
  "bulkSelectionLimitReached",
  "candidateActionPending",
  "deepLinkItem",
  "toggleAllLoadedCandidates",
  "toggleCandidateSelection",
  "pickCandidate",
  "toggleCart",
  "openDetail",
  "requestCandidateDelete",
  "restoreCandidateFromRemovedList",
  "canLoadMoreCandidates",
  "selectedBulkCandidateIds",
  "hasListUrlState",
  "bulkDialogState",
  "reviewBulkDialogOpen",
  "setSelectedCandidateIds",
  "beginReviewBulk",
  "startConfirmedReviewBulk",
  "retryVisibleReviewBulk",
  "abandonVisibleReviewBulk",
  "updateReviewBulkDialogOpen",
] as const;

export function reviewQueueSidebarProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewQueueSidebarKeys)[number]>,
) {
  return reviewViewProps(model, reviewQueueSidebarKeys);
}

const reviewCandidateEditorKeys = [
  "selected",
  "deepLinkedCandidateId",
  "deepLinkDetailQuery",
  "deepLinkStatusOut",
  "restartCandidateSnapshot",
  "deepLinkFilterOut",
  "updateReviewListState",
  "reviewSort",
  "reviewStatus",
  "deepLinkLoadedOut",
  "openDetail",
  "authoritativeRecoveryCandidate",
  "recoveryDetailQuery",
  "reopenMutation",
  "restoreCandidateFromRemovedList",
  "selectedActionable",
  "retryCandidateLoad",
  "searchInputRef",
  "query",
  "setQueryEdit",
  "runSearch",
  "searchQuery",
  "stopSearch",
  "form",
  "activeSelectedHit",
  "categoriesQuery",
  "latInvalid",
  "lngInvalid",
  "coordsOutOfKorea",
  "canSave",
  "candidateActionPending",
  "resolveMutation",
  "queueScope",
  "nearbyConflict",
  "setForm",
  "cancelCategoryMatch",
  "setCategoryEdited",
  "resolveSelected",
  "setNearbyConflict",
  "submitResolveCommand",
  "resultsRef",
  "activeQuery",
  "result",
  "opinionHits",
  "selectableHits",
  "opinionRequested",
  "gemini",
  "opinionQuery",
  "opinionResult",
  "requestOpinion",
  "applyGemini",
  "selectHit",
  "candidateAdvancePending",
  "candidateInitialLoading",
  "candidateLoadError",
  "queueCompleted",
  "candidateAdvanceError",
  "isRemovedView",
  "retryCandidateAdvance",
] as const;

export function reviewCandidateEditorProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewCandidateEditorKeys)[number]>,
) {
  return reviewViewProps(model, reviewCandidateEditorKeys);
}

const reviewCandidateMapKeys = [
  "externalResolutionEnabled",
  "mapPlaces",
  "form",
  "mapHitEntries",
  "selectHit",
] as const;

export function reviewCandidateMapProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewCandidateMapKeys)[number]>,
) {
  return reviewViewProps(model, reviewCandidateMapKeys);
}

const reviewCandidateDetailDialogKeys = [
  "detailId",
  "detailDeletePending",
  "setDetailId",
  "candidateActionPending",
  "reopenMutation",
  "requestCandidateReopen",
  "setDetailDeletePending",
  "detailDeleteSnapshotRef",
  "candidates",
  "candidatePages",
  "queueScope",
  "selectionScopeEpochRef",
  "candidatesKey",
  "reviewUndoStateRef",
  "detailCandidate",
  "updateReviewUndoState",
  "setCandidateActionError",
  "setReviewUndoError",
  "reviewListStateRef",
  "removeCandidateSelections",
  "reconcileFailedCandidateSelection",
  "candidatesKeyRef",
  "queueScopeRef",
  "markCandidateCacheRefreshError",
  "queryClient",
  "selectedCandidateIdRef",
  "advanceAfterProcessing",
  "clearProcessedCandidateParam",
  "initialSelectionDoneRef",
  "setQueueCompleted",
  "setSelectedCandidateSnapshot",
  "setSelectedId",
] as const;

export function reviewCandidateDetailDialogProps(
  model: Pick<
    ReviewWorkspaceModel,
    (typeof reviewCandidateDetailDialogKeys)[number]
  >,
) {
  return reviewViewProps(model, reviewCandidateDetailDialogKeys);
}

const reviewCandidateDeleteDialogKeys = [
  "deleteTarget",
  "deleteTargetScopeRef",
  "setDeleteTarget",
  "candidateActionPending",
  "deleteTargetActionable",
  "queueScopeRef",
  "deleteCandidatesMutation",
  "setCandidateActionError",
] as const;

export function reviewCandidateDeleteDialogProps(
  model: Pick<
    ReviewWorkspaceModel,
    (typeof reviewCandidateDeleteDialogKeys)[number]
  >,
) {
  return reviewViewProps(model, reviewCandidateDeleteDialogKeys);
}

const reviewShortcutDialogKeys = [
  "shortcutHelpOpen",
  "setShortcutHelpOpen",
] as const;

export function reviewShortcutDialogProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewShortcutDialogKeys)[number]>,
) {
  return reviewViewProps(model, reviewShortcutDialogKeys);
}

const reviewQueueFiltersKeys = [
  "reviewStatus",
  "updateReviewListState",
  "isRemovedView",
  "groupDim",
  "groupValue",
  "facetsQuery",
  "reviewSort",
  "isDomestic",
  "queueReason",
  "sourceKind",
  "groundingStatus",
] as const;

export function reviewQueueFiltersProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewQueueFiltersKeys)[number]>,
) {
  return reviewViewProps(model, reviewQueueFiltersKeys);
}

const reviewQueueNewItemsKeys = [
  "newCandidatesQuery",
  "newCandidateNotice",
  "restartCandidateSnapshot",
] as const;

export function reviewQueueNewItemsProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewQueueNewItemsKeys)[number]>,
) {
  return reviewViewProps(model, reviewQueueNewItemsKeys);
}

const reviewQueueRefreshErrorKeys = [
  "candidateAppendError",
  "candidatesQuery",
  "candidateCacheRefreshError",
  "candidatePaginationContractError",
  "candidateSnapshotRefetchError",
  "restartCandidateSnapshot",
  "retryCandidateLoad",
] as const;

export function reviewQueueRefreshErrorProps(
  model: Pick<
    ReviewWorkspaceModel,
    (typeof reviewQueueRefreshErrorKeys)[number]
  >,
) {
  return reviewViewProps(model, reviewQueueRefreshErrorKeys);
}

const reviewReprocessCartKeys = [
  "cart",
  "reprocessStage",
  "setReprocessStage",
  "reprocessMutation",
  "setCart",
] as const;

export function reviewReprocessCartProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewReprocessCartKeys)[number]>,
) {
  return reviewViewProps(model, reviewReprocessCartKeys);
}

const reviewQueueRowsKeys = [
  "candidates",
  "candidateAdvancePending",
  "candidateAdvanceError",
  "retryCandidateAdvance",
  "candidateInitialLoading",
  "candidateLoadError",
  "retryCandidateLoad",
  "deepLinkedCandidateId",
  "restartCandidateSnapshot",
  "queueCompleted",
  "isRemovedView",
  "selected",
  "selectedCandidateSet",
  "cartSet",
  "bulkSelectableLoadedCandidateIds",
  "allLoadedCandidatesSelected",
  "someLoadedCandidatesSelected",
  "bulkSelectionLimitReached",
  "candidateActionPending",
  "deepLinkItem",
  "toggleAllLoadedCandidates",
  "toggleCandidateSelection",
  "pickCandidate",
  "toggleCart",
  "openDetail",
  "requestCandidateDelete",
  "restoreCandidateFromRemovedList",
  "canLoadMoreCandidates",
  "candidatesQuery",
] as const;

export function reviewQueueRowsProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewQueueRowsKeys)[number]>,
) {
  return reviewViewProps(model, reviewQueueRowsKeys);
}

const reviewDeepLinkNoticeKeys = [
  "deepLinkStatusOut",
  "selected",
  "restartCandidateSnapshot",
  "deepLinkFilterOut",
  "updateReviewListState",
  "reviewSort",
  "reviewStatus",
  "deepLinkLoadedOut",
] as const;

export function reviewDeepLinkNoticeProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewDeepLinkNoticeKeys)[number]>,
) {
  return reviewViewProps(model, reviewDeepLinkNoticeKeys);
}

const reviewCandidateSummaryKeys = ["selected", "openDetail"] as const;

export function reviewCandidateSummaryProps(
  model: Pick<
    ReviewWorkspaceModel,
    (typeof reviewCandidateSummaryKeys)[number]
  >,
) {
  return reviewViewProps(model, reviewCandidateSummaryKeys);
}

const reviewCandidateActionsKeys = [
  "selected",
  "authoritativeRecoveryCandidate",
  "recoveryDetailQuery",
  "reopenMutation",
  "restoreCandidateFromRemovedList",
  "selectedActionable",
  "retryCandidateLoad",
  "resultsRef",
  "activeQuery",
  "result",
  "searchQuery",
  "opinionHits",
  "selectableHits",
  "activeSelectedHit",
  "opinionRequested",
  "gemini",
  "opinionQuery",
  "opinionResult",
  "requestOpinion",
  "applyGemini",
  "selectHit",
  "searchInputRef",
  "query",
  "setQueryEdit",
  "runSearch",
  "stopSearch",
  "form",
  "categoriesQuery",
  "latInvalid",
  "lngInvalid",
  "coordsOutOfKorea",
  "canSave",
  "candidateActionPending",
  "resolveMutation",
  "queueScope",
  "nearbyConflict",
  "setForm",
  "cancelCategoryMatch",
  "setCategoryEdited",
  "resolveSelected",
  "setNearbyConflict",
  "submitResolveCommand",
] as const;

export function reviewCandidateActionsProps(
  model: Pick<
    ReviewWorkspaceModel,
    (typeof reviewCandidateActionsKeys)[number]
  >,
) {
  return reviewViewProps(model, reviewCandidateActionsKeys);
}

const reviewEmptySelectionKeys = [
  "candidateAdvancePending",
  "candidateInitialLoading",
  "candidateLoadError",
  "queueCompleted",
  "candidateAdvanceError",
  "isRemovedView",
  "retryCandidateLoad",
  "deepLinkedCandidateId",
  "restartCandidateSnapshot",
  "retryCandidateAdvance",
] as const;

export function reviewEmptySelectionProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewEmptySelectionKeys)[number]>,
) {
  return reviewViewProps(model, reviewEmptySelectionKeys);
}

const reviewQueueContentsKeys = [
  "candidates",
  "candidateAdvancePending",
  "candidateAdvanceError",
  "retryCandidateAdvance",
  "candidateInitialLoading",
  "candidateLoadError",
  "retryCandidateLoad",
  "deepLinkedCandidateId",
  "restartCandidateSnapshot",
  "queueCompleted",
  "isRemovedView",
  "selected",
  "selectedCandidateSet",
  "cartSet",
  "bulkSelectableLoadedCandidateIds",
  "allLoadedCandidatesSelected",
  "someLoadedCandidatesSelected",
  "bulkSelectionLimitReached",
  "candidateActionPending",
  "deepLinkItem",
  "toggleAllLoadedCandidates",
  "toggleCandidateSelection",
  "pickCandidate",
  "toggleCart",
  "openDetail",
  "requestCandidateDelete",
  "restoreCandidateFromRemovedList",
] as const;

export function reviewQueueContentsProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewQueueContentsKeys)[number]>,
) {
  return reviewViewProps(model, reviewQueueContentsKeys);
}

const reviewPlaceSearchKeys = [
  "searchInputRef",
  "query",
  "setQueryEdit",
  "runSearch",
  "searchQuery",
  "stopSearch",
] as const;

export function reviewPlaceSearchProps(
  model: Pick<ReviewWorkspaceModel, (typeof reviewPlaceSearchKeys)[number]>,
) {
  return reviewViewProps(model, reviewPlaceSearchKeys);
}

const reviewCandidateConfirmationKeys = [
  "form",
  "activeSelectedHit",
  "categoriesQuery",
  "latInvalid",
  "lngInvalid",
  "coordsOutOfKorea",
  "canSave",
  "selectedActionable",
  "candidateActionPending",
  "resolveMutation",
  "selected",
  "queueScope",
  "nearbyConflict",
  "setForm",
  "cancelCategoryMatch",
  "setCategoryEdited",
  "resolveSelected",
  "setNearbyConflict",
  "submitResolveCommand",
] as const;

export function reviewCandidateConfirmationProps(
  model: Pick<
    ReviewWorkspaceModel,
    (typeof reviewCandidateConfirmationKeys)[number]
  >,
) {
  return reviewViewProps(model, reviewCandidateConfirmationKeys);
}

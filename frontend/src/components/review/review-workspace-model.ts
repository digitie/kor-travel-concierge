"use client";

import { type ReviewCandidatesKey } from "@/components/review/useReviewQueue";
import {
  type ReviewBulkDialogState,
  type ReviewBulkIntent,
} from "@/components/ReviewBulkPanel";
import type {
  CandidateDetail,
  CandidateReviewState,
  CandidateUndoDescriptor,
  DeleteCandidateResult,
  DestinationSummary,
  ListEnvelope,
  PlaceSearchHit,
  ReprocessStage,
  UnmatchedCandidate,
} from "@/lib/api";
import { ApiRequestError, REVIEW_BULK_SELECTION_MAX } from "@/lib/api";
import { categoryDisplayLabel } from "@/lib/display-labels";
import { formatDateTimeShort } from "@/lib/format";
import {
  summarizeReviewBulkProgress,
  type ReviewBulkState,
} from "@/lib/review-bulk";
import {
  candidateActionFailureDecision,
  settleCandidateDeletes,
  type CandidateDetailRevalidation,
} from "@/lib/review-candidate-cache";
import {
  candidateMatchesReviewListState,
  isReviewCandidateActionable,
  reviewCandidateMatchesStatus,
  type ReviewListState,
} from "@/lib/review-list-state";
import {
  isPlaceHitSelectable,
  type NearbyPlaceCandidate,
  type ReviewResolutionForm,
  type SelectedPlaceHit,
} from "@/lib/review-provenance";
import {
  confirmCandidateDeleteDetail,
  deleteResponseMatchesConfirmedDetail,
  type ReviewUndoAttempt,
  type ReviewUndoState,
} from "@/lib/review-undo";
import type {
  InfiniteData,
  UseInfiniteQueryResult,
  UseQueryResult,
} from "@tanstack/react-query";
import { createReviewUiStore, type ReviewFormState } from "./review-ui-store";

export type ResolveCommand = {
  candidateId: number;
  expectedRevision: number;
  clientOperationId: string;
  candidateName: string;
  visibleIndex: number;
  orderedCandidateIds: number[];
  loadedPageCount: number;
  queueScope: string;
  workflowEpoch: number;
  candidatesKey: ReviewCandidatesKey;
  action: "create_place" | "ignore";
  form: ReviewResolutionForm;
  selectedHit: SelectedPlaceHit | null;
  duplicate?: {
    resolution: "merge_existing" | "create_new";
    placeId?: number;
  };
};

export type ResolveCommandDraft = Omit<ResolveCommand, "clientOperationId">;

export type DeleteCandidateTarget = Pick<
  UnmatchedCandidate,
  "id" | "ai_place_name" | "state_revision"
>;

export type DeleteCandidatesResult = Awaited<
  ReturnType<typeof settleCandidateDeletes>
> & {
  responses: ReadonlyMap<number, DeleteCandidateResult>;
};

export class CandidateForwardAttemptError extends Error {
  readonly clientOperationId: string;
  readonly requestStatus: number | null;
  readonly expectedRevision: number;
  readonly responseReceived: boolean;
  readonly response: DeleteCandidateResult | null;

  constructor(
    cause: unknown,
    clientOperationId: string,
    expectedRevision: number,
    responseReceived: boolean,
    response: DeleteCandidateResult | null,
  ) {
    super(
      cause instanceof Error ? cause.message : "후보 처리 요청에 실패했습니다.",
    );
    this.name = "CandidateForwardAttemptError";
    this.clientOperationId = clientOperationId;
    this.requestStatus =
      !responseReceived && cause instanceof ApiRequestError
        ? cause.status
        : null;
    this.expectedRevision = expectedRevision;
    this.responseReceived = responseReceived;
    this.response = response;
  }
}

export class CandidateResolveAttemptError extends Error {
  readonly requestStatus: number | null;
  readonly originalError: unknown;

  constructor(cause: unknown) {
    super(
      cause instanceof Error ? cause.message : "후보 처리 요청에 실패했습니다.",
    );
    this.name = "CandidateResolveAttemptError";
    this.requestStatus = cause instanceof ApiRequestError ? cause.status : null;
    this.originalError = cause;
  }
}

export function candidateDeleteReconciliationRequestStatus(
  error: unknown,
  authoritative: CandidateDetailRevalidation | undefined,
  candidateId: number,
): number | null {
  if (!(error instanceof CandidateForwardAttemptError)) {
    return error instanceof ApiRequestError ? error.status : null;
  }
  const requestStatus = error.requestStatus;
  if (requestStatus != null && requestStatus < 500) return requestStatus;
  if (authoritative?.status !== "success") return requestStatus;
  const confirmed = confirmCandidateDeleteDetail({
    detail: authoritative.detail,
    candidateId,
    expectedRevision: error.expectedRevision,
    clientOperationId: error.clientOperationId,
  });
  if (!confirmed) return 200;
  if (!error.responseReceived) return requestStatus;
  return deleteResponseMatchesConfirmedDetail({
    response: error.response,
    confirmed,
    candidateId,
    clientOperationId: error.clientOperationId,
  })
    ? requestStatus
    : 200;
}

export type ReopenCommand = {
  descriptor: CandidateUndoDescriptor;
  candidateName: string;
  expectedReviewState: CandidateReviewState;
  source: "snackbar" | "removed_list" | "detail";
  undoAttempt: ReviewUndoAttempt | null;
  queueScope: string;
  workflowEpoch: number;
  selectedCandidateId: number | null;
  detailCandidateId: number | null;
  detailGeneration: number;
};

export type ReopenRequestResult = {
  request: { kind: "success" } | { kind: "error"; status: number | null };
  error: unknown | null;
};

export type PendingCandidateAdvance = {
  processedIds: number[];
  anchorIndex: number;
  orderedCandidateIds: number[];
  loadedPageCount: number;
};

export type ReviewUi = ReturnType<
  typeof createReviewUiStore<PendingCandidateAdvance, NearbyConflict>
>;

export type NearbyConflict = {
  command: ResolveCommand;
  places: NearbyPlaceCandidate[];
};

export function hitPlace(
  hit: PlaceSearchHit,
  placeId: number,
): DestinationSummary {
  return {
    place_id: placeId,
    name: hit.name,
    description: null,
    gemini_enriched_description: null,
    latitude: hit.latitude ?? 0,
    longitude: hit.longitude ?? 0,
    category: hit.category,
    official_address: hit.address,
    road_address: hit.road_address,
    is_geocoded: true,
    mention_count: 0,
    source_channel_count: 0,
    source_videos: [],
  };
}

// location_hint는 종종 AI가 쓴 장황한 문장("인천 (영상 설명에 언급)", "불확실함 (…)")이라
// 그대로 붙이면 검색이 망가진다. 괄호 설명을 떼고, 불확실/미상류는 힌트로 쓰지 않는다.
function cleanLocationHint(hint: string | null): string {
  if (!hint) return "";
  const stripped = hint
    .replace(/\([^)]*\)/g, " ") // 괄호 안 설명 제거
    .replace(/\s+/g, " ")
    .trim();
  if (!stripped) return "";
  if (/불확실|불명확|미상|없음|모름|unknown|n\/?a/i.test(stripped)) return "";
  // 앞쪽 2단어 정도의 지역명만 사용(예: "서울 강남" 유지, 긴 설명은 절단).
  return stripped.split(" ").slice(0, 2).join(" ");
}

export function buildHintedQuery(candidate: UnmatchedCandidate): string {
  const name = candidate.ai_place_name.trim();
  const hint = cleanLocationHint(candidate.location_hint);
  if (hint && !name.toLowerCase().includes(hint.toLowerCase())) {
    return `${hint} ${name}`;
  }
  return name;
}

export function candidateCategoryForm(candidate: UnmatchedCandidate) {
  return {
    category: categoryDisplayLabel(
      candidate.candidate_category ?? candidate.candidate_category_code,
    ),
    categoryCode: candidate.candidate_category_code ?? "0",
  };
}

export function candidateFailureShouldAdvance(
  detailRevalidation: CandidateDetailRevalidation | undefined,
  reviewListState: ReviewListState,
): boolean {
  if (!detailRevalidation) return false;
  const actionableInCurrentFilter = Boolean(
    detailRevalidation.status === "success" &&
      isReviewCandidateActionable(detailRevalidation.detail.list_item) &&
      candidateMatchesReviewListState(
        detailRevalidation.detail,
        reviewListState,
      ),
  );
  return (
    candidateActionFailureDecision(
      detailRevalidation,
      actionableInCurrentFilter,
    ) === "advance"
  );
}

function reviewBulkIntent(
  state: Exclude<ReviewBulkState, { status: "idle" }>,
): ReviewBulkIntent {
  if (state.draft.scope.kind === "filter") {
    // 현재 UI의 filter 전체 진입점은 needs_review 해외 제외만 제공한다.
    // 다른 filter action이 추가되면 별도 사용자 문구와 버튼 계약부터 확장한다.
    if (state.draft.action !== "ignore") {
      throw new Error("지원하지 않는 검수 filter 일괄 작업입니다.");
    }
    return { action: "ignore", scope: "foreign_filter" };
  }
  if (state.draft.action === "delete") {
    return { action: "delete", scope: "selection" };
  }
  if (state.draft.action === "reopen") {
    return { action: "reopen", scope: "selection" };
  }
  return { action: "ignore", scope: "selection" };
}

export function reviewBulkDialogState(
  state: ReviewBulkState,
): ReviewBulkDialogState | null {
  if (state.status === "idle") return null;
  const intent = reviewBulkIntent(state);
  if (state.status === "previewing") return { phase: "previewing", intent };
  if (state.status === "confirm") {
    return {
      phase: "ready",
      intent,
      exactCount: state.preview.total,
      expiresAtLabel: formatDateTimeShort(state.preview.expires_at),
    };
  }
  if (state.status === "executing") {
    return {
      phase: "running",
      intent,
      processed: state.progress.processed,
      total: state.progress.total,
    };
  }
  if (state.status === "completed") {
    return {
      phase: "succeeded",
      intent,
      processed: state.progress.processed,
      total: state.progress.total,
    };
  }
  if (state.status === "partial") {
    const conflictCount = state.progress.conflicts.length;
    const failedCount = state.progress.failed.length;
    const canRetryFailed =
      failedCount > 0 && failedCount <= REVIEW_BULK_SELECTION_MAX;
    const retryMessage =
      failedCount > REVIEW_BULK_SELECTION_MAX && conflictCount > 0
        ? `처리 실패 ${failedCount.toLocaleString("ko-KR")}건은 한 번에 다시 확인할 수 없어 목록에서 최대 ${REVIEW_BULK_SELECTION_MAX.toLocaleString("ko-KR")}건씩 나누어 선택해야 합니다. 상태 충돌 ${conflictCount.toLocaleString("ko-KR")}건도 자동 재실행하지 않습니다.`
        : failedCount > REVIEW_BULK_SELECTION_MAX
          ? `처리 실패 ${failedCount.toLocaleString("ko-KR")}건은 한 번에 다시 확인할 수 없습니다. 목록에서 최대 ${REVIEW_BULK_SELECTION_MAX.toLocaleString("ko-KR")}건씩 나누어 선택해 주세요.`
          : failedCount > 0 && conflictCount > 0
            ? `처리 실패 ${failedCount.toLocaleString("ko-KR")}건만 다시 확인할 수 있습니다. 상태 충돌 ${conflictCount.toLocaleString("ko-KR")}건은 자동 재실행하지 않으며 새 목록에서 직접 다시 선택해야 합니다.`
            : failedCount > 0
              ? `처리 실패 ${failedCount.toLocaleString("ko-KR")}건을 새 미리보기로 다시 확인할 수 있습니다.`
              : `상태 충돌 ${conflictCount.toLocaleString("ko-KR")}건은 자동 재실행하지 않습니다. 새 목록에서 최신 상태를 확인한 뒤 직접 다시 선택해 주세요.`;
    return {
      phase: "partial",
      intent,
      processed: state.progress.processed,
      total: state.progress.total,
      conflictCount,
      failedCount,
      canRetryFailed,
      message: retryMessage,
    };
  }
  if (state.status === "expired") {
    return {
      phase: "expired",
      intent,
      message: state.message,
      ...(state.progress ? { progress: state.progress } : {}),
    };
  }
  const executeProgress =
    state.phase === "execute"
      ? summarizeReviewBulkProgress(state.progress)
      : state.phase === "terminal"
        ? state.progress
        : undefined;
  return {
    phase: "failed",
    intent,
    message: state.message,
    retryable: state.retryable,
    retryMode: state.phase === "preview" ? "preview" : "execute",
    abandonable: state.phase !== "preview",
    failureKind:
      state.phase === "preview"
        ? state.retryable
          ? "retryable"
          : "fatal"
        : state.phase === "execute"
          ? "retryable"
          : state.terminalKind,
    ...(executeProgress ? { progress: executeProgress } : {}),
    currentChunkOutcomeUnknown:
      state.phase === "execute" ||
      (state.phase === "terminal" && state.terminalKind === "contract"),
  };
}

export function reprocessStageLabel(stage: ReprocessStage) {
  if (stage === "correction") return "교정부터";
  if (stage === "poi") return "POI 추출부터";
  return "자막 수집부터";
}

export function reviewCoordinateValidation({
  form,
  selected,
  selectedActionable,
  formCandidateId,
  activeSelectedHit,
}: {
  form: ReviewFormState;
  selected: UnmatchedCandidate | null;
  selectedActionable: boolean;
  formCandidateId: number | null;
  activeSelectedHit: SelectedPlaceHit | null;
}) {
  const latInvalid =
    Boolean(form.latitude) && !Number.isFinite(Number(form.latitude));
  const lngInvalid =
    Boolean(form.longitude) && !Number.isFinite(Number(form.longitude));
  const coordsFilled =
    Boolean(form.latitude) &&
    Boolean(form.longitude) &&
    !latInvalid &&
    !lngInvalid;
  const coordsOutOfKorea =
    coordsFilled &&
    (Number(form.latitude) < 33 ||
      Number(form.latitude) > 39 ||
      Number(form.longitude) < 124 ||
      Number(form.longitude) > 132);
  const canSave =
    selected != null &&
    selectedActionable &&
    formCandidateId === selected.id &&
    Boolean(form.name.trim()) &&
    coordsFilled &&
    (activeSelectedHit == null || isPlaceHitSelectable(activeSelectedHit.hit));
  return { latInvalid, lngInvalid, coordsOutOfKorea, canSave };
}

export function reviewQueueLoadStatus({
  pendingCandidateAdvance,
  candidatePaginationContractError,
  candidatesQuery,
  deepLinkNotFound,
  deepLinkedCandidateId,
  deepLinkDetailQuery,
  candidates,
  candidateCacheRefreshError,
}: {
  pendingCandidateAdvance: PendingCandidateAdvance | null;
  candidatePaginationContractError: string | null;
  candidatesQuery: UseInfiniteQueryResult<
    InfiniteData<ListEnvelope<UnmatchedCandidate>, unknown>,
    Error
  >;
  deepLinkNotFound: string | null;
  deepLinkedCandidateId: number | null;
  deepLinkDetailQuery: UseQueryResult<CandidateDetail, Error>;
  candidates: UnmatchedCandidate[];
  candidateCacheRefreshError: string | null;
}) {
  const candidateAdvancePending = pendingCandidateAdvance != null;
  const candidateAdvanceError = candidateAdvancePending
    ? (candidatePaginationContractError ??
      (candidatesQuery.isFetchNextPageError
        ? (candidatesQuery.error?.message ?? "다음 후보를 불러오지 못했습니다.")
        : null))
    : null;
  const candidateLoadError =
    deepLinkNotFound ??
    (deepLinkedCandidateId != null && deepLinkDetailQuery.isError
      ? (deepLinkDetailQuery.error?.message ??
        `검수 후보 #${deepLinkedCandidateId}을(를) 찾을 수 없습니다.`)
      : null) ??
    candidatePaginationContractError ??
    (candidatesQuery.isError || candidatesQuery.isFetchNextPageError
      ? (candidatesQuery.error?.message ?? "검수 후보를 불러오지 못했습니다.")
      : null);
  const candidateSnapshotRefetchError =
    candidates.length > 0 &&
    candidatesQuery.isRefetchError &&
    !candidatesQuery.isFetchNextPageError;
  const candidateAppendError =
    candidateCacheRefreshError ??
    (candidates.length > 0
      ? (candidatePaginationContractError ??
        (candidatesQuery.isFetchNextPageError
          ? (candidatesQuery.error?.message ??
            "다음 후보를 불러오지 못했습니다.")
          : candidateSnapshotRefetchError
            ? (candidatesQuery.error?.message ??
              "현재 검수 목록을 다시 확인하지 못했습니다.")
            : null))
      : null);
  return {
    candidateAdvancePending,
    candidateAdvanceError,
    candidateLoadError,
    candidateSnapshotRefetchError,
    candidateAppendError,
  };
}

export function recoveryCandidateAuthority(
  selected: UnmatchedCandidate | null,
  detail: CandidateDetail | undefined,
  isError: boolean,
  isRefetchError: boolean,
) {
  const listItem = detail?.list_item;
  const candidate = detail?.candidate;
  if (
    !selected ||
    isError ||
    isRefetchError ||
    !listItem ||
    !candidate ||
    listItem.id !== selected.id ||
    candidate.id !== selected.id ||
    listItem.review_state === "needs_review" ||
    candidate.review_state !== listItem.review_state ||
    candidate.state_revision !== listItem.state_revision ||
    !listItem.undo ||
    listItem.undo.candidate_id !== listItem.id ||
    listItem.undo.token.length === 0
  ) {
    return null;
  }
  return listItem;
}

export function reviewCandidateAccess({
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
}: {
  deepLinkItem: UnmatchedCandidate | null;
  reviewStatus: "needs_review" | "removed";
  deepLinkDetail: CandidateDetail | null;
  reviewListState: ReviewListState;
  loadedCandidateIds: Set<number>;
  isRemovedView: boolean;
  selected: UnmatchedCandidate | null;
  deepLinkedCandidateId: number | null;
  candidatesQuery: UseInfiniteQueryResult<
    InfiniteData<ListEnvelope<UnmatchedCandidate>, unknown>,
    Error
  >;
  deepLinkDetailQuery: UseQueryResult<CandidateDetail, Error>;
}) {
  const deepLinkStatusOut = Boolean(
    deepLinkItem && !reviewCandidateMatchesStatus(deepLinkItem, reviewStatus),
  );
  const deepLinkFilterOut = Boolean(
    deepLinkDetail &&
      !deepLinkStatusOut &&
      !candidateMatchesReviewListState(deepLinkDetail, reviewListState),
  );
  const deepLinkLoadedOut = Boolean(
    deepLinkItem &&
      !deepLinkStatusOut &&
      !deepLinkFilterOut &&
      !loadedCandidateIds.has(deepLinkItem.id),
  );
  const selectedActionable = Boolean(
    !isRemovedView &&
      selected &&
      isReviewCandidateActionable(selected) &&
      (deepLinkedCandidateId == null
        ? !(
            candidatesQuery.isRefetchError &&
            !candidatesQuery.isFetchNextPageError
          )
        : deepLinkItem?.id === selected.id &&
          !deepLinkStatusOut &&
          !deepLinkDetailQuery.isError),
  );
  return {
    deepLinkStatusOut,
    deepLinkFilterOut,
    deepLinkLoadedOut,
    selectedActionable,
  };
}

export function reviewDetailActionState({
  hasListUrlState,
  candidates,
  candidatesQuery,
  deepLinkedCandidateId,
  deepLinkDetailQuery,
  detailId,
  deepLinkItem,
  deleteTarget,
}: {
  hasListUrlState: boolean;
  candidates: UnmatchedCandidate[];
  candidatesQuery: UseInfiniteQueryResult<
    InfiniteData<ListEnvelope<UnmatchedCandidate>, unknown>,
    Error
  >;
  deepLinkedCandidateId: number | null;
  deepLinkDetailQuery: UseQueryResult<CandidateDetail, Error>;
  detailId: number | null;
  deepLinkItem: UnmatchedCandidate | null;
  deleteTarget: UnmatchedCandidate | null;
}) {
  const candidateInitialLoading =
    !hasListUrlState ||
    (candidates.length === 0 && candidatesQuery.isLoading) ||
    (deepLinkedCandidateId != null && deepLinkDetailQuery.isLoading);
  const detailCandidate =
    detailId == null
      ? null
      : (candidates.find((candidate) => candidate.id === detailId) ??
        (deepLinkItem?.id === detailId ? deepLinkItem : null));
  const deleteTargetActionable = Boolean(
    deleteTarget &&
      isReviewCandidateActionable(
        deepLinkItem?.id === deleteTarget.id ? deepLinkItem : deleteTarget,
      ),
  );
  return { candidateInitialLoading, detailCandidate, deleteTargetActionable };
}

export function reviewTriageProgress({
  selected,
  candidates,
  candidateTotal,
  reviewUndoState,
}: {
  selected: UnmatchedCandidate | null;
  candidates: UnmatchedCandidate[];
  candidateTotal: number;
  reviewUndoState: ReviewUndoState;
}) {
  const triageQueueIndex = selected
    ? candidates.findIndex((candidate) => candidate.id === selected.id)
    : -1;
  const triagePosition = triageQueueIndex >= 0 ? triageQueueIndex + 1 : 0;
  const triageRemaining = Math.max(
    candidateTotal - (triagePosition > 0 ? triagePosition : 0),
    0,
  );
  const lastProcessed = reviewUndoState.current;
  return { triagePosition, triageRemaining, lastProcessed };
}

export function reviewCandidateActionStatus({
  resolveMutation,
  deleteCandidatesMutation,
  reopenMutation,
  detailDeletePending,
  deepLinkValidationPending,
  bulkBlocksCandidateActions,
}: {
  resolveMutation: { isPending: boolean };
  deleteCandidatesMutation: { isPending: boolean };
  reopenMutation: { isPending: boolean };
  detailDeletePending: boolean;
  deepLinkValidationPending: boolean;
  bulkBlocksCandidateActions: boolean;
}) {
  const candidateActionPending =
    resolveMutation.isPending ||
    deleteCandidatesMutation.isPending ||
    reopenMutation.isPending ||
    detailDeletePending ||
    deepLinkValidationPending ||
    bulkBlocksCandidateActions;
  return { candidateActionPending };
}

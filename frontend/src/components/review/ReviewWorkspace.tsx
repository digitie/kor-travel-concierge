"use client";

import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ExternalLinkIcon,
  InfoIcon,
  KeyboardIcon,
  Loader2Icon,
  RefreshCwIcon,
  RotateCcwIcon,
  SearchIcon,
  SquareIcon,
} from "lucide-react";

import {
  ApiRequestError,
  deleteCandidate,
  getCandidateDetail,
  listCategories,
  matchCategory,
  reprocessVideos,
  reopenCandidate,
  REVIEW_BULK_SELECTION_MAX,
  resolveCandidate,
  RUN_QUEUE_QUERY_KEY,
  type CandidateReviewState,
  type CandidateUndoDescriptor,
  type DeleteCandidateResult,
  type DestinationGroupDim,
  type DestinationSummary,
  type PlaceOpinion,
  type PlaceSearchHit,
  type ReprocessStage,
  type ResolveCandidateInput,
  type ReviewGroundingStatus,
  type ReviewBulkScope,
  type ReviewQueueReason,
  type ReviewSourceFacets,
  type ReviewSourceKind,
  type UnmatchedCandidate,
} from "@/lib/api";
import {
  categoryDisplayLabel,
  groundingStatusLabel,
  queueReasonLabel,
  sourceKindLabel,
} from "@/lib/display-labels";
import { formatDateTimeShort, youtubeWatchUrl } from "@/lib/format";
import {
  buildCreatePlaceResolution,
  isPlaceHitStorageAllowed,
  parseNearbyPlaceConflict,
  type NearbyPlaceCandidate,
  type ReviewResolutionForm,
  type SelectedPlaceHit,
} from "@/lib/review-provenance";
import {
  candidateActionFailureDecision,
  candidateFailureSelectionDecision,
  getCandidateFromReviewPageCache,
  prepareCandidateReopenCaches,
  reconcileCandidateReopenCaches,
  reconcileProcessedCandidateCaches,
  revalidateCandidateActionFailure,
  settleCandidateDeletes,
  type CandidateDetailRevalidation,
} from "@/lib/review-candidate-cache";
import {
  candidateMatchesReviewListState,
  DEFAULT_REVIEW_LIST_STATE,
  isCurrentReviewWorkflow,
  isReviewCandidateActionable,
  parseReviewCandidateId,
  parseReviewListState,
  reconcileReviewSearchDraft,
  REVIEW_GROUNDING_STATUSES,
  REVIEW_QUEUE_REASONS,
  REVIEW_SOURCE_KINDS,
  reviewCandidateMatchesStatus,
  reviewListStateToForeignBulkFilter,
  writeReviewListState,
  type ReviewListState,
} from "@/lib/review-list-state";
import {
  applyReviewActionSuccess,
  captureReviewUndoAttempt,
  classifyReviewUndoOutcome,
  confirmCandidateDeleteDetail,
  deleteResponseMatchesConfirmedDetail,
  dismissReviewUndo,
  INITIAL_REVIEW_UNDO_STATE,
  isCurrentReviewUndoAttempt,
  parseReviewUndoHandoff,
  reconcileReviewUndoAfterActionFailure,
  REVIEW_UNDO_HANDOFF_STORAGE_KEY,
  waitForCandidateOperationMarker,
  type ReviewUndoAttempt,
  type ReviewUndoState,
} from "@/lib/review-undo";
import { useIsMobile } from "@/lib/use-is-mobile";
import { usePersistedState } from "@/lib/use-persisted-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { AppShell } from "@/components/AppShell";
import { CandidateDetailView } from "@/components/CandidateDetailView";
import { ReviewUndoSnackbar } from "@/components/ReviewUndoSnackbar";
import {
  CandidateTable,
  candidateReviewStateLabel,
} from "@/components/review/CandidateTable";
import { ConfirmForm } from "@/components/review/ConfirmForm";
import { SearchResultsPanel } from "@/components/review/SearchResultsPanel";
import { useCandidateSearch } from "@/components/review/useCandidateSearch";
import {
  REVIEW_SHORTCUTS,
  useReviewKeyboard,
} from "@/components/review/useReviewKeyboard";
import {
  useReviewQueue,
  type ReviewCandidatesKey,
} from "@/components/review/useReviewQueue";
import {
  ReviewBulkPanel,
  type ReviewBulkDialogState,
  type ReviewBulkIntent,
} from "@/components/ReviewBulkPanel";
import { VWorldMap } from "@/components/VWorldMap";
import {
  summarizeReviewBulkProgress,
  type ReviewBulkState,
} from "@/lib/review-bulk";
import { useReviewBulk } from "@/lib/use-review-bulk";

type ResolveCommand = {
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

type ResolveCommandDraft = Omit<ResolveCommand, "clientOperationId">;

type DeleteCandidateTarget = Pick<
  UnmatchedCandidate,
  "id" | "ai_place_name" | "state_revision"
>;

type DeleteCandidatesResult = Awaited<
  ReturnType<typeof settleCandidateDeletes>
> & {
  responses: ReadonlyMap<number, DeleteCandidateResult>;
};

class CandidateForwardAttemptError extends Error {
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
    super(cause instanceof Error ? cause.message : "후보 처리 요청에 실패했습니다.");
    this.name = "CandidateForwardAttemptError";
    this.clientOperationId = clientOperationId;
    this.requestStatus =
      !responseReceived && cause instanceof ApiRequestError ? cause.status : null;
    this.expectedRevision = expectedRevision;
    this.responseReceived = responseReceived;
    this.response = response;
  }
}

class CandidateResolveAttemptError extends Error {
  readonly requestStatus: number | null;
  readonly originalError: unknown;

  constructor(cause: unknown) {
    super(cause instanceof Error ? cause.message : "후보 처리 요청에 실패했습니다.");
    this.name = "CandidateResolveAttemptError";
    this.requestStatus = cause instanceof ApiRequestError ? cause.status : null;
    this.originalError = cause;
  }
}

function candidateDeleteReconciliationRequestStatus(
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

type ReopenCommand = {
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

type ReopenRequestResult = {
  request:
    | { kind: "success" }
    | { kind: "error"; status: number | null };
  error: unknown | null;
};

type PendingCandidateAdvance = {
  processedIds: number[];
  anchorIndex: number;
  orderedCandidateIds: number[];
  loadedPageCount: number;
};

type NearbyConflict = {
  command: ResolveCommand;
  places: NearbyPlaceCandidate[];
};

function hitPlace(hit: PlaceSearchHit, placeId: number): DestinationSummary {
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

function buildHintedQuery(candidate: UnmatchedCandidate): string {
  const name = candidate.ai_place_name.trim();
  const hint = cleanLocationHint(candidate.location_hint);
  if (hint && !name.toLowerCase().includes(hint.toLowerCase())) {
    return `${hint} ${name}`;
  }
  return name;
}

function candidateCategoryForm(candidate: UnmatchedCandidate) {
  return {
    category: categoryDisplayLabel(
      candidate.candidate_category ?? candidate.candidate_category_code,
    ),
    categoryCode: candidate.candidate_category_code ?? "0",
  };
}

function candidateFailureShouldAdvance(
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

function reviewBulkDialogState(
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
      ...(state.progress
        ? { progress: state.progress }
        : {}),
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

export function ReviewWorkspace() {
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
  const [cart, setCart] = usePersistedState<string[]>("ktc.review.cart", []);
  const [reprocessStage, setReprocessStage] =
    useState<ReprocessStage>("transcript");
  const cartSet = useMemo(() => new Set(cart), [cart]);
  const toggleCart = useCallback(
    (videoId: string) => {
      setCart((prev) =>
        prev.includes(videoId)
          ? prev.filter((v) => v !== videoId)
          : [...prev, videoId],
      );
    },
    [setCart],
  );
  const reprocessMutation = useMutation({
    mutationFn: () => reprocessVideos(cart, reprocessStage),
    onSuccess: () => {
      setCart([]);
      queryClient.invalidateQueries({ queryKey: RUN_QUEUE_QUERY_KEY });
    },
  });
  const previousQueueScopeRef = useRef(queueScope);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<number[]>([]);
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
    [bulkSelectableLoadedCandidateIds],
  );
  const removeCandidateSelections = useCallback(
    (candidateIds: readonly number[]) => {
      if (candidateIds.length === 0) return;
      const removed = new Set(candidateIds);
      setSelectedCandidateIds((current) =>
        current.filter((candidateId) => !removed.has(candidateId)),
      );
    },
    [],
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
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedCandidateSnapshot, setSelectedCandidateSnapshot] =
    useState<UnmatchedCandidate | null>(null);
  const selectionScopeEpochRef = useRef(0);
  const validationGenerationRef = useRef(0);
  const [deepLinkValidationPending, setDeepLinkValidationPending] =
    useState(false);
  const invalidateCandidateWorkflow = useCallback(() => {
    selectionScopeEpochRef.current += 1;
    validationGenerationRef.current += 1;
    setDeepLinkValidationPending(false);
  }, []);
  const initialSelectionDoneRef = useRef(false);
  const [deepLinkNotFound, setDeepLinkNotFound] = useState<string | null>(null);
  const previousDeepLinkIdRef = useRef<number | null>(null);
  const preserveSelectionOnDeepLinkClearRef = useRef(false);
  const pendingCandidateAdvanceRef = useRef<PendingCandidateAdvance | null>(null);
  const [pendingCandidateAdvance, setPendingCandidateAdvance] =
    useState<PendingCandidateAdvance | null>(null);
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
    [],
  );
  const [queueCompleted, setQueueCompleted] = useState(false);
  const [candidateActionError, setCandidateActionError] = useState<string | null>(
    null,
  );
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

  // URL 후보가 바뀌면 필터는 보존하고 단건 상세 조회가 끝날 때까지 기존 snapshot을 비운다.
  /* eslint-disable react-hooks/set-state-in-effect */
  useLayoutEffect(() => {
    if (previousDeepLinkIdRef.current === deepLinkedCandidateId) return;
    previousDeepLinkIdRef.current = deepLinkedCandidateId;
    invalidateCandidateWorkflow();
    setDeepLinkNotFound(null);
    if (deepLinkedCandidateId == null) {
      if (preserveSelectionOnDeepLinkClearRef.current) {
        preserveSelectionOnDeepLinkClearRef.current = false;
        initialSelectionDoneRef.current = true;
        return;
      }
      initialSelectionDoneRef.current = false;
      setSelectedCandidateSnapshot(null);
      setSelectedId(null);
      return;
    }
    preserveSelectionOnDeepLinkClearRef.current = false;
    initialSelectionDoneRef.current = false;
    setSelectedCandidateSnapshot(null);
    setSelectedId(deepLinkedCandidateId);
  }, [deepLinkedCandidateId, invalidateCandidateWorkflow]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const selected = useMemo(
    () => {
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
    },
    [
      candidates,
      deepLinkedCandidateId,
      deepLinkItem,
      selectedCandidateSnapshot,
      selectedId,
    ],
  );
  const recoveryDetailQuery = useQuery({
    queryKey: ["candidate-detail", selected?.id ?? null],
    queryFn: () => getCandidateDetail(selected?.id as number),
    enabled: Boolean(selected && selected.review_state !== "needs_review"),
  });
  const authoritativeRecoveryCandidate = useMemo(() => {
    const detail = recoveryDetailQuery.data;
    const listItem = detail?.list_item;
    const candidate = detail?.candidate;
    if (
      !selected ||
      recoveryDetailQuery.isError ||
      recoveryDetailQuery.isRefetchError ||
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
  }, [
    recoveryDetailQuery.data,
    recoveryDetailQuery.isError,
    recoveryDetailQuery.isRefetchError,
    selected,
  ]);

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
  const [queryEdit, setQueryEdit] = useState<string | null>(null);
  const query = queryEdit ?? (selected ? buildHintedQuery(selected) : "");
  const externalResolutionEnabled = !isRemovedView && selectedActionable;
  const {
    activeQuery,
    searchQuery,
    result,
    allHits,
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
      resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [result]);

  const isMobile = useIsMobile();
  // 단축키 `/` 포커스 대상과 `?` 도움말 오버레이 상태(T-187).
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false);
  const [detailId, setDetailIdState] = useState<number | null>(null);
  const detailIdRef = useRef<number | null>(null);
  const detailGenerationRef = useRef(0);
  const setDetailId = useCallback(
    (
      next:
        | number
        | null
        | ((current: number | null) => number | null),
    ) => {
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

  const [form, setForm] = useState({
    name: "",
    latitude: "",
    longitude: "",
    category: "",
    // 강제 카테고리 코드(드롭다운). category(label)는 코드 선택 시 함께 채운다.
    categoryCode: "",
  });
  const [formCandidateId, setFormCandidateId] = useState<number | null>(null);
  const [categoryEdited, setCategoryEdited] = useState(false);
  const [selectedHit, setSelectedHit] = useState<SelectedPlaceHit | null>(null);
  const [nearbyConflict, setNearbyConflict] = useState<NearbyConflict | null>(null);
  const categoryMatchAbortRef = useRef<AbortController | null>(null);
  const categoryMatchRequestRef = useRef(0);
  const selectedCandidateIdRef = useRef<number | null>(selected?.id ?? null);

  useLayoutEffect(() => {
    if (previousQueueScopeRef.current === queueScope) return;
    previousQueueScopeRef.current = queueScope;
    invalidateCandidateWorkflow();
    initialSelectionDoneRef.current = false;
    updatePendingCandidateAdvance(null);
    selectedCandidateIdRef.current = null;
    if (!detailDeletePending) detailDeleteSnapshotRef.current = null;
    deleteTargetScopeRef.current = null;
    setQueueCompleted(false);
    setSelectedCandidateIds([]);
    setSelectedCandidateSnapshot(null);
    setSelectedId(null);
    setNearbyConflict(null);
    setDeleteTarget(null);
    setDetailId(null);
    setCandidateActionError(null);
    clearCandidateCacheRefreshError();
  }, [
    clearCandidateCacheRefreshError,
    detailDeletePending,
    invalidateCandidateWorkflow,
    queueScope,
    setDetailId,
    updatePendingCandidateAdvance,
  ]);

  const cancelCategoryMatch = useCallback(() => {
    categoryMatchRequestRef.current += 1;
    categoryMatchAbortRef.current?.abort();
    categoryMatchAbortRef.current = null;
  }, []);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (externalResolutionEnabled) return;
    cancelCategoryMatch();
    setQueryEdit(null);
    setSelectedHit(null);
  }, [cancelCategoryMatch, externalResolutionEnabled]);
  /* eslint-enable react-hooks/set-state-in-effect */

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
  }, [selected?.id, selectedId]);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const candidateId = selected?.id ?? null;
    if (candidateId === formCandidateId) return;
    cancelCategoryMatch();
    setQueryEdit(null);
    setFormCandidateId(candidateId);
    setSelectedHit(null);
    setNearbyConflict(null);
    setCategoryEdited(false);
    setForm(
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
  }, [
    cancelCategoryMatch,
    formCandidateId,
    prepareCandidate,
    queueScopeRef,
    selected,
  ]);
  /* eslint-enable react-hooks/set-state-in-effect */

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
    [isMobile, router, setDetailId],
  );
  const clearCandidateParam = useCallback((preserveSelection = false) => {
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
  }, [commitReviewUrl, invalidateCandidateWorkflow]);
  const clearProcessedCandidateParam = useCallback(
    (candidateId: number, preserveSelection = true) => {
      const url = new URL(window.location.href);
      if (parseReviewCandidateId(url.searchParams) !== candidateId) return false;
      invalidateCandidateWorkflow();
      preserveSelectionOnDeepLinkClearRef.current = preserveSelection;
      url.searchParams.delete("candidate");
      setDeepLinkNotFound(null);
      commitReviewUrl(url.searchParams);
      return true;
    },
    [commitReviewUrl, invalidateCandidateWorkflow],
  );
  const pickCandidate = useCallback(
    (
      candidate: UnmatchedCandidate,
      {
        autoSearch = true,
        preserveWorkflow = false,
      }: { autoSearch?: boolean; preserveWorkflow?: boolean } = {},
    ) => {
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
    },
    [
      cancelCategoryMatch,
      clearCandidateParam,
      invalidateCandidateWorkflow,
      prepareCandidate,
      queueScopeRef,
      reviewListStateRef,
      updatePendingCandidateAdvance,
    ],
  );

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
    [candidates, pickCandidate],
  );

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
        nextSnapshotId == null ? null : (remainingById.get(nextSnapshotId) ?? null);
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
    ],
  );

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
        orderedCandidateIds.findIndex((candidateId) => candidateId === processedId);
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
    }, [
      candidatePages.length,
      candidates,
      clearProcessedCandidateParam,
      continueCandidateAdvance,
      removeCandidateSelections,
    ]);

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
    ],
  );

  /* eslint-disable react-hooks/set-state-in-effect */
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
  /* eslint-enable react-hooks/set-state-in-effect */

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
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
        setDeepLinkNotFound(
          deepLinkDetailQuery.error?.message ??
            `검수 후보 #${deepLinkedId}을(를) 찾을 수 없습니다.`,
        );
        initialSelectionDoneRef.current = true;
        return;
      }
      setDeepLinkNotFound(null);
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
  ]);
  /* eslint-enable react-hooks/set-state-in-effect */

  /* eslint-disable react-hooks/set-state-in-effect */
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
  ]);
  /* eslint-enable react-hooks/set-state-in-effect */

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
          if (!target) throw new Error(`삭제 후보 #${candidateId} 정보가 없습니다.`);
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
              throw new Error("삭제 응답이 요청 후보의 완료 상태와 일치하지 않습니다.");
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
        const target = targets.find((candidate) => candidate.id === candidateId);
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
          .map(({ id, reason }) =>
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
                target?.ai_place_name ?? `후보 #${failedId ?? result.attemptedIds[0]}`,
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
      setCandidateActionError(`후보 삭제 결과를 확인하지 못했습니다: ${error.message}`);
      const activeCandidatesKey = candidatesKeyRef.current;
      const activeQueueScope = queueScopeRef.current;
      const failureRefresh = await revalidateCandidateActionFailure(queryClient, {
        candidateIds,
        activePageKey: activeCandidatesKey,
        fetchCandidateDetail: getCandidateDetail,
      });
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

  function selectHit(hit: PlaceSearchHit) {
    if (!selected || !isPlaceHitStorageAllowed(hit)) return;
    cancelCategoryMatch();
    const candidateId = selected.id;
    const nextSelectedHit: SelectedPlaceHit = {
      candidateId,
      hit,
      query: result?.query ?? activeQuery,
      searchedAt: result?.searched_at ?? new Date().toISOString(),
      selectedAt: new Date().toISOString(),
    };
    setSelectedHit(nextSelectedHit);
    setNearbyConflict(null);
    setFormCandidateId(candidateId);
    setForm((prev) => ({
      ...prev,
      name: hit.name,
      latitude: hit.latitude == null ? "" : String(hit.latitude),
      longitude: hit.longitude == null ? "" : String(hit.longitude),
    }));
    // 검색결과 카테고리 매칭이 되면 그 값을 쓰고, 실패하면 후보의 기본 카테고리를 유지한다.
    // 사용자가 드롭다운을 직접 바꾼 뒤에는 자동 매칭으로 덮어쓰지 않는다.
    if (hit.category && !categoryEdited) {
      const controller = new AbortController();
      categoryMatchAbortRef.current = controller;
      const requestId = ++categoryMatchRequestRef.current;
      void matchCategory(hit.category, controller.signal)
        .then((match) => {
          if (
            !match ||
            controller.signal.aborted ||
            requestId !== categoryMatchRequestRef.current ||
            candidateId !== selectedCandidateIdRef.current
          ) {
            return;
          }
          setForm((prev) => ({
            ...prev,
            categoryCode: match.code,
            category: match.label,
          }));
        })
        // 카테고리 자동 매핑 실패는 후보 선택 자체를 막지 않는다.
        .catch(() => {})
        .finally(() => {
          if (requestId === categoryMatchRequestRef.current) {
            categoryMatchAbortRef.current = null;
          }
        });
    }
  }
  function applyGemini(gemini: PlaceOpinion) {
    // Gemini 의견도 카테고리는 덮어쓰지 않는다(드롭다운이 단일 출처).
    cancelCategoryMatch();
    setSelectedHit(null);
    setNearbyConflict(null);
    setFormCandidateId(selected?.id ?? null);
    setForm((prev) => ({
      ...prev,
      name: gemini.best_name ?? prev.name,
      latitude: gemini.latitude != null ? String(gemini.latitude) : prev.latitude,
      longitude:
        gemini.longitude != null ? String(gemini.longitude) : prev.longitude,
    }));
  }

  const activeSelectedHit =
    selectedHit?.candidateId === selected?.id ? selectedHit : null;
  const mapHitEntries = useMemo(
    () =>
      allHits
        .filter(
          (hit) =>
            isPlaceHitStorageAllowed(hit) &&
            hit.latitude != null &&
            hit.longitude != null,
        )
        .map((hit, index) => ({ placeId: index + 1, hit })),
    [allHits],
  );
  const mapPlaces = useMemo<DestinationSummary[]>(() => {
    if (!externalResolutionEnabled) return [];
    const hits = mapHitEntries.map(({ hit, placeId }) => hitPlace(hit, placeId));
    const lat = Number(form.latitude);
    const lng = Number(form.longitude);
    if (Number.isFinite(lat) && Number.isFinite(lng) && form.latitude) {
      hits.unshift({
        place_id: 9999,
        name: form.name || "선택 위치",
        description: null,
        gemini_enriched_description: null,
        latitude: lat,
        longitude: lng,
        category: form.category || null,
        official_address: activeSelectedHit?.hit.address ?? null,
        road_address: activeSelectedHit?.hit.road_address ?? null,
        is_geocoded: true,
        mention_count: 0,
        source_channel_count: 0,
        source_videos: [],
      });
    }
    return hits;
  }, [activeSelectedHit, externalResolutionEnabled, form, mapHitEntries]);

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
          throw new Error("후보 처리 응답이 요청 후보의 완료 상태와 일치하지 않습니다.");
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
      const failureRefresh = await revalidateCandidateActionFailure(queryClient, {
        candidateIds: [command.candidateId],
        activePageKey: activeCandidatesKey,
        fetchCandidateDetail: getCandidateDetail,
      });
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
      if (isCurrentCommand && undoReconciliation.outcome === "confirmed_committed") {
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
          setCandidateActionError(
            "후보의 최신 상태를 확인하지 못했습니다.",
          );
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
    [commitReviewUrl],
  );

  const reopenMutation = useMutation({
    mutationFn: async (command: ReopenCommand): Promise<ReopenRequestResult> => {
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
        if (completionWasCurrent && reconciliation.detail.status === "success") {
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
      deleteCandidatesMutation.isPending,
      detailDeletePending,
      reopenMutation,
      queueScopeRef,
      resolveMutation.isPending,
    ],
  );
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
    candidatesKeyRef,
    clearCandidateCacheRefreshError,
    queryClient,
    queueScopeRef,
    resetReviewScope,
  ]);

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
  }, [queryClient, restartCandidateSnapshot, updateReviewUndoState]);
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
    ],
  );
  const startConfirmedReviewBulk = useCallback(() => {
    updateReviewUndoState(dismissReviewUndo);
    setReviewUndoError(null);
    confirmReviewBulk();
  }, [confirmReviewBulk, updateReviewUndoState]);
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
  ]);
  const abandonVisibleReviewBulk = useCallback(() => {
    const needsRefresh =
      (reviewBulkState.status === "expired" &&
        reviewBulkState.progress != null) ||
      (reviewBulkState.status === "error" &&
        reviewBulkState.phase !== "preview");
    resetReviewBulkWorkflow();
    if (needsRefresh) void handleReviewBulkSettled();
  }, [
    handleReviewBulkSettled,
    resetReviewBulkWorkflow,
    reviewBulkState,
  ]);

  // 좌표 입력 검증: 숫자 여부(차단) + 대한민국 대략 범위(경고만, 저장은 허용).
  const latInvalid = Boolean(form.latitude) && !Number.isFinite(Number(form.latitude));
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
    (activeSelectedHit == null || isPlaceHitStorageAllowed(activeSelectedHit.hit));
  const candidateAdvancePending = pendingCandidateAdvance != null;
  const candidateAdvanceError =
    candidateAdvancePending
      ? candidatePaginationContractError ??
        (candidatesQuery.isFetchNextPageError
          ? candidatesQuery.error?.message ?? "다음 후보를 불러오지 못했습니다."
          : null)
      : null;
  const candidateLoadError =
    deepLinkNotFound ??
    (deepLinkedCandidateId != null && deepLinkDetailQuery.isError
      ? deepLinkDetailQuery.error?.message ??
        `검수 후보 #${deepLinkedCandidateId}을(를) 찾을 수 없습니다.`
      : null) ??
    candidatePaginationContractError ??
    (candidatesQuery.isError || candidatesQuery.isFetchNextPageError
      ? candidatesQuery.error?.message ?? "검수 후보를 불러오지 못했습니다."
      : null);
  const candidateSnapshotRefetchError =
    candidates.length > 0 &&
    candidatesQuery.isRefetchError &&
    !candidatesQuery.isFetchNextPageError;
  const candidateAppendError =
    candidateCacheRefreshError ??
    (candidates.length > 0
      ? candidatePaginationContractError ??
        (candidatesQuery.isFetchNextPageError
          ? candidatesQuery.error?.message ?? "다음 후보를 불러오지 못했습니다."
          : candidateSnapshotRefetchError
            ? candidatesQuery.error?.message ??
              "현재 검수 목록을 다시 확인하지 못했습니다."
            : null)
      : null);
  const candidateActionPending =
    resolveMutation.isPending ||
    deleteCandidatesMutation.isPending ||
    reopenMutation.isPending ||
    detailDeletePending ||
    deepLinkValidationPending ||
    bulkBlocksCandidateActions;

  // 처리 단축키(T-187). 개별 액션은 각자의 가드(canSave·selectedActionable·undo
  // 존재)를 다시 확인해, 전역 keydown 가드를 통과해도 부적합 상태에서는 무해하다.
  useReviewKeyboard({
    enabled: hasListUrlState,
    onNextCandidate: () => pickCandidateOffset(1),
    onPrevCandidate: () => pickCandidateOffset(-1),
    onSelectHit: (ordinal) => {
      const hit = allHits[ordinal - 1];
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
  const triageQueueIndex = selected
    ? candidates.findIndex((candidate) => candidate.id === selected.id)
    : -1;
  const triagePosition = triageQueueIndex >= 0 ? triageQueueIndex + 1 : 0;
  const triageRemaining = Math.max(
    candidateTotal - (triagePosition > 0 ? triagePosition : 0),
    0,
  );
  const lastProcessed = reviewUndoState.current;
  const modeToggle = (
    <div
      role="group"
      aria-label="검수 화면 모드"
      className="inline-flex overflow-hidden rounded-lg border"
    >
      {(["triage", "table"] as const).map((mode) => (
        <button
          key={mode}
          type="button"
          aria-pressed={reviewMode === mode}
          onClick={() => setReviewMode(mode)}
          className="px-2.5 py-1 text-xs font-medium transition-colors aria-pressed:bg-primary aria-pressed:text-primary-foreground"
        >
          {mode === "triage" ? "처리 모드" : "목록/관리"}
        </button>
      ))}
    </div>
  );

  return (
    <AppShell
      title="검수 큐"
      actions={
        <div className="flex items-center gap-2">
          {modeToggle}
          <Button
            type="button"
            size="icon-xs"
            variant="ghost"
            aria-label="검수 단축키 도움말"
            title="단축키 도움말 (?)"
            onClick={() => setShortcutHelpOpen(true)}
          >
            <KeyboardIcon />
          </Button>
          <Badge variant="secondary">
            {candidates.length}/{candidateTotal}개 불러옴
          </Badge>
        </div>
      }
      contentClassName="flex min-h-0 flex-1 flex-col p-0"
      viewportLocked
    >
      <div
        className={
          isTriage
            ? "grid h-full min-h-0 flex-1 grid-cols-1 lg:grid-cols-[15rem_minmax(0,1fr)_minmax(0,1fr)] lg:overflow-hidden"
            : "grid h-full min-h-0 flex-1 grid-cols-1 lg:grid-cols-3 lg:overflow-hidden"
        }
      >
        {isTriage ? (
          <aside className="flex min-h-0 max-h-[40vh] flex-col gap-3 overflow-y-auto border-b p-3 lg:h-full lg:max-h-none lg:border-r lg:border-b-0">
            <div className="flex items-center justify-between gap-2">
              <p className="px-1 text-xs font-medium text-muted-foreground">
                처리 진행
              </p>
              <Button
                type="button"
                size="icon-xs"
                variant="ghost"
                aria-label="검수 후보 수동 새로고침"
                title="현재 조건을 첫 페이지부터 새로고침"
                disabled={candidatesQuery.isFetching}
                onClick={() => {
                  void restartCandidateSnapshot();
                  void facetsQuery.refetch();
                }}
              >
                <RefreshCwIcon
                  className={
                    candidatesQuery.isFetching ? "animate-spin" : undefined
                  }
                />
              </Button>
            </div>
            <div className="rounded-xl border p-3">
              <p className="text-2xl font-semibold tabular-nums">
                {triagePosition > 0 ? triagePosition : "–"}
                <span className="text-sm font-normal text-muted-foreground">
                  {" "}
                  / {candidateTotal}
                </span>
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {queueCompleted
                  ? "현재 조건을 모두 처리했습니다."
                  : `남은 후보 약 ${triageRemaining}건`}
              </p>
            </div>
            {lastProcessed ? (
              <div className="flex flex-col gap-2 rounded-xl border border-primary/30 bg-primary/5 p-3">
                <p className="text-xs font-medium">최근 처리</p>
                <p className="truncate text-sm" title={lastProcessed.candidateName}>
                  {lastProcessed.candidateName}
                </p>
                <p className="text-xs text-muted-foreground">
                  {lastProcessed.action === "create_place" ||
                  lastProcessed.action === "match_existing"
                    ? "저장됨"
                    : lastProcessed.action === "ignore"
                      ? "제외됨"
                      : "삭제됨"}
                </p>
                <Button
                  type="button"
                  size="xs"
                  variant="outline"
                  disabled={candidateActionPending}
                  onClick={() => {
                    const entry = reviewUndoStateRef.current.current;
                    if (!entry) return;
                    requestCandidateReopen(
                      {
                        id: entry.descriptor.candidate_id,
                        ai_place_name: entry.candidateName,
                        review_state: entry.expectedReviewState,
                        undo: entry.descriptor,
                      },
                      "snackbar",
                    );
                  }}
                >
                  <RotateCcwIcon data-icon="inline-start" />
                  되돌리기 (U)
                </Button>
                {reviewUndoError ? (
                  <p role="alert" className="text-xs text-destructive">
                    {reviewUndoError}
                  </p>
                ) : null}
              </div>
            ) : (
              <p className="rounded-xl border p-3 text-xs text-muted-foreground">
                처리한 후보가 여기에 표시되고 U로 되돌릴 수 있습니다.
              </p>
            )}
            <p className="mt-auto rounded-lg border border-dashed p-2 text-[11px] leading-relaxed text-muted-foreground">
              J/K 다음·이전 · 1–9 검색결과 · Enter 저장 · X 제외 · U 되돌리기 · /
              검색 · ? 도움말. 필터·일괄 처리는 &ldquo;목록/관리&rdquo; 모드에서.
            </p>
          </aside>
        ) : (
        <aside className="flex min-h-0 max-h-[48vh] flex-col gap-2 overflow-hidden border-b p-3 lg:h-full lg:max-h-none lg:border-r lg:border-b-0">
          <div className="flex items-center justify-between gap-2">
            <p className="px-1 text-xs font-medium text-muted-foreground">
              {isRemovedView ? "제외·삭제된 후보" : "검수 대기 후보"}
            </p>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                size="icon-xs"
                variant="ghost"
                aria-label="검수 후보 수동 새로고침"
                title="현재 조건을 첫 페이지부터 새로고침"
                disabled={candidatesQuery.isFetching}
                onClick={() => {
                  void restartCandidateSnapshot();
                  void facetsQuery.refetch();
                }}
              >
                <RefreshCwIcon
                  className={candidatesQuery.isFetching ? "animate-spin" : undefined}
                />
              </Button>
              <Badge variant="secondary">
                {candidates.length}/{candidateTotal}
              </Badge>
            </div>
          </div>
          <div className="flex min-h-0 flex-1 flex-col gap-2">
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto lg:flex lg:flex-col lg:gap-2 lg:space-y-0 lg:overflow-hidden">
              <ReviewQueueSearch
                value={reviewQuery}
                onDebouncedChange={updateReviewQuery}
              />
          <div className="grid grid-cols-2 gap-1.5 pb-1">
            <Select
              value={reviewStatus}
              onValueChange={(value) =>
                updateReviewListState({
                  status: value === "removed" ? "removed" : "needs_review",
                })
              }
            >
              <SelectTrigger className="w-full" aria-label="검수 후보 상태">
                <SelectValue>
                  {isRemovedView ? "제외·삭제됨" : "검수 대기"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="needs_review">검수 대기</SelectItem>
                  <SelectItem value="removed">제외·삭제됨</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <Select
              value={groupDim}
              onValueChange={(value) => {
                if (!value) return;
                updateReviewListState({
                  groupDim: value as DestinationGroupDim,
                  groupValue: null,
                });
              }}
            >
              <SelectTrigger className="w-full" aria-label="검수 그룹 기준">
                <SelectValue>{groupDimLabel(groupDim)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="none">전체</SelectItem>
                  <SelectItem value="channel">유튜버별</SelectItem>
                  <SelectItem value="playlist">재생목록별</SelectItem>
                  <SelectItem value="keyword">검색어별</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            {groupDim !== "none" ? (
              <Select
                value={groupValue ?? ""}
                onValueChange={(value) => {
                  updateReviewListState({ groupValue: value || null });
                }}
              >
                <SelectTrigger className="w-full" aria-label="그룹 값 선택">
                  <SelectValue placeholder={`${groupDimLabel(groupDim)} 선택`}>
                    {groupValueLabel(groupDim, groupValue, facetsQuery.data)}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {groupOptions(groupDim, facetsQuery.data).map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label} ({opt.count})
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            ) : (
              <div />
            )}
            <Select
              value={reviewSort}
              onValueChange={(value) =>
                updateReviewListState({
                  sort: value === "newest" ? "newest" : "oldest",
                })
              }
            >
              <SelectTrigger className="w-full" aria-label="검수 후보 정렬">
                <SelectValue>
                  {reviewSort === "oldest" ? "오래된 후보 우선" : "최신 후보 우선"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="oldest">오래된 후보 우선</SelectItem>
                  <SelectItem value="newest">최신 후보 우선</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <Select
              value={isDomestic == null ? "all" : String(isDomestic)}
              onValueChange={(value) =>
                updateReviewListState({
                  isDomestic:
                    value === "true" ? true : value === "false" ? false : null,
                })
              }
            >
              <SelectTrigger className="w-full" aria-label="국내 여부 필터">
                <SelectValue>
                  {isDomestic === true
                    ? "국내 판정만"
                    : isDomestic === false
                      ? "해외 판정만"
                      : "국내 여부 전체"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="all">국내 여부 전체</SelectItem>
                  <SelectItem value="true">국내 판정만</SelectItem>
                  <SelectItem value="false">해외 판정만</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <Select
              value={queueReason ?? "all"}
              onValueChange={(value) =>
                updateReviewListState({
                  queueReason:
                    !value || value === "all"
                      ? null
                      : (value as ReviewQueueReason),
                })
              }
            >
              <SelectTrigger className="w-full" aria-label="검수 대기 사유 필터">
                <SelectValue>
                  {queueReason ? queueReasonLabel(queueReason) : "대기 사유 전체"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent className="max-h-72">
                <SelectGroup>
                  <SelectItem value="all">대기 사유 전체</SelectItem>
                  {REVIEW_QUEUE_REASONS.map((reason) => (
                    <SelectItem key={reason} value={reason}>
                      {queueReasonLabel(reason)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Select
              value={sourceKind ?? "all"}
              onValueChange={(value) =>
                updateReviewListState({
                  sourceKind:
                    !value || value === "all"
                      ? null
                      : (value as ReviewSourceKind),
                })
              }
            >
              <SelectTrigger className="w-full" aria-label="후보 출처 필터">
                <SelectValue>
                  {sourceKind ? sourceKindLabel(sourceKind) : "후보 출처 전체"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent className="max-h-72">
                <SelectGroup>
                  <SelectItem value="all">후보 출처 전체</SelectItem>
                  {REVIEW_SOURCE_KINDS.map((kind) => (
                    <SelectItem key={kind} value={kind}>
                      {sourceKindLabel(kind)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Select
              value={groundingStatus ?? "all"}
              onValueChange={(value) =>
                updateReviewListState({
                  groundingStatus:
                    !value || value === "all"
                      ? null
                      : (value as ReviewGroundingStatus),
                })
              }
            >
              <SelectTrigger className="w-full" aria-label="원문 근거 필터">
                <SelectValue>
                  {groundingStatus
                    ? groundingStatusLabel(groundingStatus)
                    : "원문 근거 전체"}
                </SelectValue>
              </SelectTrigger>
              <SelectContent className="max-h-72">
                <SelectGroup>
                  <SelectItem value="all">원문 근거 전체</SelectItem>
                  {REVIEW_GROUNDING_STATUSES.map((status) => (
                    <SelectItem key={status} value={status}>
                      {groundingStatusLabel(status)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>
          {hasReviewFilters ? (
            <Button
              type="button"
              size="xs"
              variant="ghost"
              className="self-start"
              onClick={() =>
                updateReviewListState({
                  ...DEFAULT_REVIEW_LIST_STATE,
                  sort: reviewSort,
                  status: reviewStatus,
                })
              }
            >
              필터 해제
            </Button>
          ) : null}
          {facetsQuery.isError ? (
            <p role="alert" className="px-1 text-xs text-destructive">
              그룹 기준을 불러오지 못했습니다. 새로고침 버튼으로 다시 시도해 주세요.
            </p>
          ) : null}
          {newCandidatesQuery.isError ? (
            <div className="flex items-center justify-between gap-2 rounded-lg border border-destructive/30 px-2 py-1.5 text-xs text-destructive">
              <span role="alert">
                새 후보 확인에 실패해 이전 확인값은 표시하지 않습니다.
              </span>
              <Button
                type="button"
                size="xs"
                variant="ghost"
                onClick={() => void newCandidatesQuery.refetch()}
              >
                다시 확인
              </Button>
            </div>
          ) : newCandidateNotice ? (
            <div role="status" aria-live="polite">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="w-full border-primary/40 bg-primary/5"
                onClick={() => void restartCandidateSnapshot()}
              >
                {newCandidateNotice}
              </Button>
            </div>
          ) : null}
          {candidateAppendError ? (
            <div className="flex items-center justify-between gap-2 rounded-lg border border-destructive/30 px-2 py-1.5 text-xs text-destructive">
              <span role="alert">{candidateAppendError}</span>
              <Button
                type="button"
                size="xs"
                variant="outline"
                disabled={candidatesQuery.isFetchingNextPage}
                onClick={() => {
                  if (
                    candidateCacheRefreshError ||
                    candidatePaginationContractError ||
                    candidateSnapshotRefetchError
                  ) {
                    void restartCandidateSnapshot();
                  } else {
                    retryCandidateLoad();
                  }
                }}
              >
                다시 시도
              </Button>
            </div>
          ) : null}
          {deleteCandidatesMutation.error ? (
            <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive" role="alert">
              {deleteCandidatesMutation.error.message}
            </p>
          ) : null}
          {candidateActionError ? (
            <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive" role="alert">
              {candidateActionError}
            </p>
          ) : null}
          {!isRemovedView && reprocessMutation.isSuccess && reprocessMutation.data ? (
            <p className="rounded-lg bg-primary/10 px-2 py-1 text-xs text-primary">
              영상 {reprocessMutation.data.videos}개를{" "}
              {reprocessMutation.data.enqueued_jobs}개 작업으로 재처리 등록했습니다.
            </p>
          ) : null}
          {!isRemovedView && cart.length > 0 ? (
            <div className="flex flex-col gap-1.5 rounded-lg border border-primary/40 bg-primary/5 p-2">
              <p className="text-xs font-medium">
                선택한 영상 {cart.length}개 재처리
              </p>
              <Select
                value={reprocessStage}
                onValueChange={(value) =>
                  setReprocessStage(value as ReprocessStage)
                }
              >
                <SelectTrigger className="w-full" aria-label="재처리 시작 단계">
                  <SelectValue>{reprocessStageLabel(reprocessStage)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="transcript">자막 수집부터</SelectItem>
                    <SelectItem value="correction">교정부터</SelectItem>
                    <SelectItem value="poi">POI 추출부터</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              <div className="grid grid-cols-2 gap-1.5">
                <Button
                  type="button"
                  size="xs"
                  onClick={() => reprocessMutation.mutate()}
                  disabled={reprocessMutation.isPending}
                >
                  선택 재처리
                </Button>
                <Button
                  type="button"
                  size="xs"
                  variant="outline"
                  onClick={() => setCart([])}
                >
                  비우기
                </Button>
              </div>
              {reprocessMutation.error ? (
                <p className="text-xs text-destructive">
                  {reprocessMutation.error.message}
                </p>
              ) : null}
            </div>
          ) : null}
          <div className="min-h-0 lg:flex-1 lg:overflow-y-auto">
            {candidates.length === 0 ? (
              candidateAdvancePending ? (
                <div className="flex flex-col gap-2 rounded-lg border p-3 text-xs text-muted-foreground">
                  <p role="status">
                    {candidateAdvanceError
                      ? candidateAdvanceError
                      : "다음 검수 후보를 불러오는 중…"}
                  </p>
                  {candidateAdvanceError ? (
                    <Button
                      type="button"
                      size="xs"
                      variant="outline"
                      onClick={retryCandidateAdvance}
                    >
                      다시 시도
                    </Button>
                  ) : null}
                </div>
              ) : candidateInitialLoading ? (
                <p
                  role="status"
                  aria-live="polite"
                  className="rounded-lg border p-3 text-xs text-muted-foreground"
                >
                  검수 후보를 불러오는 중…
                </p>
              ) : candidateLoadError ? (
                <div className="flex flex-col gap-2 rounded-lg border border-destructive/30 p-3 text-xs text-destructive">
                  <p role="alert">{candidateLoadError}</p>
                  <div className="flex flex-wrap gap-1.5">
                    <Button
                      type="button"
                      size="xs"
                      variant="outline"
                      onClick={retryCandidateLoad}
                    >
                      다시 시도
                    </Button>
                    {deepLinkedCandidateId != null ? (
                      <Button
                        type="button"
                        size="xs"
                        variant="ghost"
                        onClick={() => void restartCandidateSnapshot()}
                      >
                        현재 목록으로
                      </Button>
                    ) : null}
                  </div>
                </div>
              ) : (
                <p
                  role={queueCompleted ? "status" : undefined}
                  className="rounded-lg border p-3 text-xs text-muted-foreground"
                >
                  {queueCompleted
                    ? isRemovedView
                      ? "현재 표시 조건에 복구할 후보가 없습니다."
                      : "현재 표시 조건의 검수 후보를 모두 처리했습니다."
                    : isRemovedView
                      ? "제외·삭제된 후보가 없습니다."
                      : "검수할 후보가 없습니다."}
                </p>
              )
            ) : (
              <CandidateTable
                candidates={candidates}
                currentCandidateId={selected?.id ?? null}
                selectedCandidateIds={selectedCandidateSet}
                cartVideoIds={cartSet}
                bulkSelectableCandidateIds={bulkSelectableLoadedCandidateIds}
                allLoadedCandidatesSelected={allLoadedCandidatesSelected}
                someLoadedCandidatesSelected={someLoadedCandidatesSelected}
                bulkSelectionLimitReached={bulkSelectionLimitReached}
                candidateActionPending={candidateActionPending}
                removedMode={isRemovedView}
                isCandidateActionable={(candidate) =>
                  isReviewCandidateActionable(
                    deepLinkItem?.id === candidate.id
                      ? deepLinkItem
                      : candidate,
                  )
                }
                onToggleAllLoadedCandidates={toggleAllLoadedCandidates}
                onToggleSelect={toggleCandidateSelection}
                onPick={pickCandidate}
                onToggleCart={toggleCart}
                onOpenDetail={openDetail}
                onRequestDelete={requestCandidateDelete}
                onRestore={restoreCandidateFromRemovedList}
              />
            )}
            {canLoadMoreCandidates ? (
              <div className="border-t bg-background p-2 lg:sticky lg:bottom-0">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="w-full"
                  disabled={candidatesQuery.isFetchingNextPage}
                  onClick={() => {
                    if (
                      !candidatesQuery.hasNextPage ||
                      candidatesQuery.isFetchingNextPage
                    ) {
                      return;
                    }
                    void candidatesQuery.fetchNextPage({ cancelRefetch: false });
                  }}
                >
                  {candidatesQuery.isFetchingNextPage ? (
                    <Loader2Icon data-icon="inline-start" className="animate-spin" />
                  ) : null}
                  후보 더 불러오기
                </Button>
              </div>
            ) : null}
          </div>
            </div>
            <ReviewBulkPanel
              mode={isRemovedView ? "removed" : "review"}
              selectedCount={selectedBulkCandidateIds.length}
              selectionLimit={REVIEW_BULK_SELECTION_MAX}
              actionsDisabled={candidateActionPending}
              foreignActionDisabled={!hasListUrlState}
              dialogState={bulkDialogState}
              dialogOpen={reviewBulkDialogOpen}
              className="shrink-0"
              onClearSelection={() => setSelectedCandidateIds([])}
              onRequestPreview={beginReviewBulk}
              onConfirm={startConfirmedReviewBulk}
              onRetry={retryVisibleReviewBulk}
              onAbandon={abandonVisibleReviewBulk}
              onDialogOpenChange={updateReviewBulkDialogOpen}
            />
          </div>
        </aside>
        )}

        <section className="flex min-h-0 flex-col gap-4 overflow-y-auto p-5">
          {selected ? (
            <>
              {deepLinkedCandidateId != null &&
              deepLinkDetailQuery.data != null &&
              deepLinkDetailQuery.isError ? (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                  <span role="alert">
                    최신 후보 상세를 다시 확인하지 못해 이전 정보를 표시합니다.
                  </span>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    disabled={deepLinkDetailQuery.isFetching}
                    onClick={() => void deepLinkDetailQuery.refetch()}
                  >
                    상세 다시 확인
                  </Button>
                </div>
              ) : null}
              {deepLinkStatusOut ? (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-warning/40 bg-warning/5 p-3 text-sm">
                  <span role="status">
                    이 후보는 현재 {candidateReviewStateLabel(selected.review_state)} 상태라 검수
                    저장·제외·삭제를 할 수 없습니다.
                  </span>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    onClick={() => void restartCandidateSnapshot()}
                  >
                    현재 목록으로
                  </Button>
                </div>
              ) : deepLinkFilterOut ? (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-primary/30 bg-primary/5 p-3 text-sm">
                  <span role="status">현재 필터 밖 후보를 단건 상세로 열었습니다.</span>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    onClick={() =>
                      updateReviewListState({
                        ...DEFAULT_REVIEW_LIST_STATE,
                        sort: reviewSort,
                        status: reviewStatus,
                      })
                    }
                  >
                    필터 해제
                  </Button>
                </div>
              ) : deepLinkLoadedOut ? (
                <p
                  role="status"
                  className="rounded-xl border border-primary/30 bg-primary/5 p-3 text-sm"
                >
                  현재 필터에는 포함되지만 아직 불러온 페이지 밖 후보입니다. 목록 전체를
                  순회하지 않고 단건 상세로 바로 열었습니다.
                </p>
              ) : null}
              <div className="flex flex-col gap-2 rounded-xl border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold">
                    {selected.ai_place_name}
                  </span>
                  <Badge variant="outline">
                    {categoryDisplayLabel(selected.candidate_category)}
                  </Badge>
                  <Badge variant="secondary">
                    {candidateReviewStateLabel(selected.review_state)}
                  </Badge>
                </div>
                {selected.location_hint ? (
                  <p className="text-xs text-muted-foreground">
                    위치 힌트: {selected.location_hint}
                  </p>
                ) : null}
                {selected.video_is_excluded &&
                selected.review_state === "needs_review" ? (
                  <p
                    role="status"
                    className="rounded-lg border border-warning/40 bg-warning/5 p-2 text-xs text-warning"
                  >
                    출처 영상은 제외 상태입니다. 후보를 복구하거나 다시 확정해도
                    영상 제외는 유지됩니다.
                  </p>
                ) : null}
                <div className="flex flex-wrap items-center gap-3">
                  <a
                    href={youtubeWatchUrl(
                      selected.video_id,
                      selected.timestamp_start,
                    )}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex w-fit items-center gap-1 text-xs text-primary hover:underline"
                  >
                    영상 보기 <ExternalLinkIcon className="size-3" />
                  </a>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    onClick={() => openDetail(selected.id)}
                  >
                    <InfoIcon data-icon="inline-start" />
                    상세 보기
                  </Button>
                </div>
              </div>

              {selected.review_state !== "needs_review" ? (
                <RemovedCandidateRecoveryPanel
                  candidate={selected}
                  authoritativeCandidate={authoritativeRecoveryCandidate}
                  verificationPending={recoveryDetailQuery.isFetching}
                  verificationError={
                    recoveryDetailQuery.isError ||
                    recoveryDetailQuery.isRefetchError
                      ? recoveryDetailQuery.error?.message ??
                        "최신 후보 상세를 확인하지 못했습니다."
                      : recoveryDetailQuery.data != null &&
                          authoritativeRecoveryCandidate == null
                        ? "후보 상태가 바뀌었거나 복구 정보가 최신 상세와 일치하지 않습니다."
                        : null
                  }
                  pending={reopenMutation.isPending}
                  onRestore={restoreCandidateFromRemovedList}
                  onVerify={() => void recoveryDetailQuery.refetch()}
                />
              ) : !selectedActionable ? (
                <div className="flex flex-col items-start gap-2 rounded-xl border border-warning/40 bg-warning/5 p-4 text-sm">
                  <p role="status">
                    최신 후보 상태를 확인하지 못해 외부 검색과 검수 액션을 잠시
                    중지했습니다.
                  </p>
                  <Button
                    type="button"
                    size="xs"
                    variant="outline"
                    onClick={() => void retryCandidateLoad()}
                  >
                    최신 상태 다시 확인
                  </Button>
                </div>
              ) : (
                <>
              <div className="flex gap-2">
                <Input
                  ref={searchInputRef}
                  aria-label="외부 장소 검색어"
                  value={query}
                  placeholder="장소명으로 검색 (Google·Kakao·Naver·Gemini)"
                  onChange={(event) => setQueryEdit(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      runSearch();
                    }
                  }}
                />
                <Button type="button" onClick={runSearch} disabled={!query.trim()}>
                  {searchQuery.isFetching ? (
                    <Loader2Icon data-icon="inline-start" className="animate-spin" />
                  ) : (
                    <SearchIcon data-icon="inline-start" />
                  )}
                  검색
                </Button>
                {searchQuery.isFetching ? (
                  <Button type="button" variant="outline" onClick={stopSearch}>
                    <SquareIcon data-icon="inline-start" />
                    검색 중지
                  </Button>
                ) : null}
              </div>

              <ConfirmForm
                form={form}
                selectedHit={activeSelectedHit}
                categories={categoriesQuery.data ?? []}
                latitudeInvalid={latInvalid}
                longitudeInvalid={lngInvalid}
                coordinatesOutOfKorea={coordsOutOfKorea}
                canSave={canSave}
                selectedActionable={selectedActionable}
                candidateActionPending={candidateActionPending}
                resolutionError={
                  resolveMutation.error &&
                  resolveMutation.variables?.candidateId === selected.id &&
                  resolveMutation.variables.queueScope === queueScope &&
                  parseNearbyPlaceConflict(resolveMutation.error) == null
                    ? resolveMutation.error.message
                    : null
                }
                nearbyConflict={
                  nearbyConflict
                    ? {
                        placeName: nearbyConflict.command.form.name,
                        places: nearbyConflict.places,
                      }
                    : null
                }
                onNameChange={(name) => setForm((prev) => ({ ...prev, name }))}
                onLatitudeChange={(latitude) =>
                  setForm((prev) => ({ ...prev, latitude }))
                }
                onLongitudeChange={(longitude) =>
                  setForm((prev) => ({ ...prev, longitude }))
                }
                onCategoryChange={(code) => {
                  cancelCategoryMatch();
                  const option = (categoriesQuery.data ?? []).find(
                    (category) => category.code === code,
                  );
                  setCategoryEdited(true);
                  setForm((prev) => ({
                    ...prev,
                    categoryCode: code,
                    category: option?.label ?? prev.category,
                  }));
                }}
                onSave={() => resolveSelected("create_place")}
                onIgnore={() => resolveSelected("ignore")}
                onDismissNearbyConflict={() => setNearbyConflict(null)}
                onMergeNearbyPlace={(place) => {
                  if (!nearbyConflict) return;
                  submitResolveCommand({
                    ...nearbyConflict.command,
                    duplicate: {
                      resolution: "merge_existing",
                      placeId: place.placeId,
                    },
                  });
                }}
                onCreateNewNearbyPlace={() => {
                  if (!nearbyConflict) return;
                  submitResolveCommand({
                    ...nearbyConflict.command,
                    duplicate: { resolution: "create_new" },
                  });
                }}
              />

              <SearchResultsPanel
                resultsRef={resultsRef}
                activeQuery={activeQuery}
                result={result}
                loading={searchQuery.isFetching}
                selectableHitCount={allHits.length}
                orderedHits={allHits}
                selectedHit={activeSelectedHit?.hit ?? null}
                opinionRequested={opinionRequested}
                opinion={gemini}
                opinionLoading={opinionQuery.isFetching}
                opinionError={opinionResult?.error}
                onRequestOpinion={requestOpinion}
                onRetryOpinion={() => void opinionQuery.refetch()}
                onApplyOpinion={applyGemini}
                onSelectHit={selectHit}
              />
                </>
              )}
            </>
          ) : (
            <div className="flex flex-col gap-2 text-sm text-muted-foreground">
              <p
                role={
                  candidateAdvancePending || candidateInitialLoading
                    ? "status"
                    : candidateLoadError
                      ? "alert"
                      : queueCompleted
                      ? "status"
                      : undefined
                }
                aria-live={candidateInitialLoading ? "polite" : undefined}
              >
                {candidateAdvancePending
                  ? candidateAdvanceError ?? "다음 검수 후보를 불러오는 중…"
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
                      : "검수할 후보가 없습니다."}
              </p>
              {!candidateInitialLoading && candidateLoadError ? (
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={retryCandidateLoad}
                  >
                    검수 후보 다시 불러오기
                  </Button>
                  {deepLinkedCandidateId != null ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => void restartCandidateSnapshot()}
                    >
                      현재 목록으로
                    </Button>
                  ) : null}
                </div>
              ) : candidateAdvanceError ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={retryCandidateAdvance}
                >
                  다음 후보 다시 불러오기
                </Button>
              ) : null}
            </div>
          )}
        </section>
        <section className="min-h-[28rem] overflow-hidden border-t lg:min-h-0 lg:border-t-0 lg:border-l">
          {externalResolutionEnabled ? (
            <VWorldMap
              places={mapPlaces}
              selectedPlaceId={form.latitude ? 9999 : null}
              onSelectPlace={(placeId) => {
                const entry = mapHitEntries.find((item) => item.placeId === placeId);
                if (entry) selectHit(entry.hit);
              }}
            />
          ) : (
            <div className="flex h-full min-h-[28rem] items-center justify-center bg-muted/20 p-6 text-center text-sm text-muted-foreground">
              복구 전용 화면에서는 외부 지도와 장소 검색을 호출하지 않습니다.
            </div>
          )}
        </section>
      </div>

      <Dialog
        open={detailId != null}
        onOpenChange={(open) => {
          if (!open && !detailDeletePending) setDetailId(null);
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>검수 후보 상세</DialogTitle>
          </DialogHeader>
          {detailId != null ? (
            <CandidateDetailView
              candidateId={detailId}
              cacheHandledByOnDeleted
              actionsDisabled={
                candidateActionPending || detailDeletePending
              }
              restorePending={
                reopenMutation.isPending &&
                reopenMutation.variables?.descriptor.candidate_id === detailId
              }
              onRestoreRequested={(candidate) =>
                requestCandidateReopen(candidate, "detail")
              }
              onDeleteStarted={(candidateId) => {
                setDetailDeletePending(true);
                detailDeleteSnapshotRef.current = {
                  candidateId,
                  visibleIndex: candidates.findIndex(
                    (candidate) => candidate.id === candidateId,
                  ),
                  orderedCandidateIds: candidates.map(
                    (candidate) => candidate.id,
                  ),
                  loadedPageCount: candidatePages.length,
                  queueScope,
                  workflowEpoch: selectionScopeEpochRef.current,
                  candidatesKey,
                };
              }}
              onDeleteFailureRevalidated={(
                candidateId,
                detailRevalidation,
                requestStatus,
                requestAttempted,
                clientOperationId,
              ) => {
                const snapshot = detailDeleteSnapshotRef.current;
                if (!snapshot || snapshot.candidateId !== candidateId) return;
                const undoReconciliation =
                  reconcileReviewUndoAfterActionFailure(
                    reviewUndoStateRef.current,
                    {
                      authoritative: detailRevalidation,
                      requestAttempted,
                      requestStatus,
                      clientOperationId,
                      candidateId,
                      candidateName:
                        detailCandidate?.ai_place_name ?? `후보 #${candidateId}`,
                      action: "delete",
                      expectedReviewState: "deleted",
                    },
                  );
                updateReviewUndoState(() => undoReconciliation.state);
                if (undoReconciliation.outcome === "confirmed_committed") {
                  setCandidateActionError(
                    `${detailCandidate?.ai_place_name ?? `후보 #${candidateId}`} 후보의 응답은 끊겼지만 최신 상태에서 삭제 완료를 확인했습니다.`,
                  );
                } else if (
                  undoReconciliation.outcome === "foreign_or_stale"
                ) {
                  setCandidateActionError(
                    `${detailCandidate?.ai_place_name ?? `후보 #${candidateId}`} 후보는 다른 작업으로 상태가 바뀌어 최신 상태를 반영했습니다.`,
                  );
                }
                if (
                  detailRevalidation?.status !== "success" ||
                  detailRevalidation.detail.list_item.review_state !==
                    "needs_review"
                ) {
                  setReviewUndoError(null);
                }
                if (
                  candidateFailureShouldAdvance(
                    detailRevalidation,
                    reviewListStateRef.current,
                  )
                ) {
                  removeCandidateSelections([candidateId]);
                }
                const advanced = reconcileFailedCandidateSelection(
                  candidateId,
                  {
                    visibleIndex: snapshot.visibleIndex,
                    orderedCandidateIds: snapshot.orderedCandidateIds,
                    loadedPageCount: snapshot.loadedPageCount,
                    queueScope: snapshot.queueScope,
                    workflowEpoch: snapshot.workflowEpoch,
                    activePageKey: candidatesKeyRef.current,
                  },
                  detailRevalidation,
                );
                if (advanced) setDetailId(null);
              }}
              onDeleteSettled={() => {
                setDetailDeletePending(false);
                detailDeleteSnapshotRef.current = null;
              }}
              onCacheRefreshFailed={() => {
                if (
                  detailDeleteSnapshotRef.current?.queueScope ===
                  queueScopeRef.current
                ) {
                  markCandidateCacheRefreshError();
                }
              }}
              onDeleted={async (result) => {
                const deletedId = result.id;
                const snapshot = detailDeleteSnapshotRef.current;
                const deletedCandidateName =
                  detailCandidate?.ai_place_name ?? `후보 #${deletedId}`;
                const activeCandidatesKey = candidatesKeyRef.current;
                const activeQueueScope = queueScopeRef.current;
                const cacheResult = await reconcileProcessedCandidateCaches(
                  queryClient,
                  {
                    ids: [deletedId],
                    capturedPageKey: snapshot?.candidatesKey,
                    activePageKey: activeCandidatesKey,
                    pageOut: snapshot != null && snapshot.visibleIndex < 0,
                  },
                );
                if (
                  cacheResult.postCommitRefreshFailed &&
                  activeQueueScope === queueScopeRef.current
                ) {
                  markCandidateCacheRefreshError();
                }
                setDetailId((current) =>
                  current === deletedId ? null : current,
                );
                if (
                  deletedId === selectedCandidateIdRef.current &&
                  snapshot?.candidateId === deletedId &&
                  snapshot.visibleIndex >= 0 &&
                  snapshot.queueScope === queueScopeRef.current &&
                  snapshot.workflowEpoch === selectionScopeEpochRef.current
                ) {
                  advanceAfterProcessing(
                    deletedId,
                    [deletedId],
                    snapshot.visibleIndex,
                    snapshot.orderedCandidateIds,
                    snapshot.loadedPageCount,
                  );
                } else {
                  removeCandidateSelections([deletedId]);
                  clearProcessedCandidateParam(deletedId, false);
                  if (deletedId === selectedCandidateIdRef.current) {
                    initialSelectionDoneRef.current = false;
                    selectedCandidateIdRef.current = null;
                    setQueueCompleted(false);
                    setSelectedCandidateSnapshot(null);
                    setSelectedId(null);
                  }
                }
                // active cache/selection 정리가 끝난 뒤에만 undo를 노출한다. 먼저
                // 노출하면 즉시 reopen과 늦은 delete reconcile이 후보를 다시 지운다.
                updateReviewUndoState((current) =>
                  applyReviewActionSuccess(current, {
                    candidateId: deletedId,
                    candidateName: deletedCandidateName,
                    action: "delete",
                    reviewState: "deleted",
                    undo: result.undo,
                  }),
                );
                setReviewUndoError(null);
              }}
            />
          ) : null}
        </DialogContent>
      </Dialog>

      {/* 행 삭제 확인 — 페이지 공용 단일 다이얼로그 */}
      <AlertDialog
        open={deleteTarget != null}
        onOpenChange={(open) => {
          if (!open) {
            deleteTargetScopeRef.current = null;
            setDeleteTarget(null);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {deleteTarget?.ai_place_name} 후보를 삭제할까요?
            </AlertDialogTitle>
            <AlertDialogDescription>
              삭제 후 제외·삭제 목록에서 이 후보를 복구할 수 있습니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={
                <Button type="button" variant="outline" size="sm">
                  취소
                </Button>
              }
            />
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={candidateActionPending || !deleteTargetActionable}
              onClick={() => {
                if (
                  deleteTarget &&
                  deleteTargetActionable &&
                  deleteTargetScopeRef.current === queueScopeRef.current
                ) {
                  deleteCandidatesMutation.mutate([deleteTarget]);
                } else if (deleteTarget) {
                  setCandidateActionError(
                    `${deleteTarget.ai_place_name} 후보는 표시 조건이 바뀌어 삭제하지 않았습니다. 현재 목록에서 다시 선택해 주세요.`,
                  );
                }
                deleteTargetScopeRef.current = null;
                setDeleteTarget(null);
              }}
            >
              삭제
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {reviewUndoState.current ? (
        <ReviewUndoSnackbar
          candidateName={reviewUndoState.current.candidateName}
          actionLabel={
            reviewUndoState.current.action === "create_place" ||
            reviewUndoState.current.action === "match_existing"
              ? "저장"
              : reviewUndoState.current.action === "ignore"
                ? "제외"
                : "삭제"
          }
          pending={
            reopenMutation.isPending &&
            reopenMutation.variables?.source === "snackbar" &&
            reopenMutation.variables.descriptor.token ===
              reviewUndoState.current.descriptor.token
          }
          disabled={candidateActionPending}
          error={reviewUndoError}
          onUndo={() => {
            const entry = reviewUndoStateRef.current.current;
            if (!entry) return;
            requestCandidateReopen(
              {
                id: entry.descriptor.candidate_id,
                ai_place_name: entry.candidateName,
                review_state: entry.expectedReviewState,
                undo: entry.descriptor,
              },
              "snackbar",
            );
          }}
          onDismiss={() => {
            updateReviewUndoState(dismissReviewUndo);
            setReviewUndoError(null);
          }}
        />
      ) : null}

      <Dialog open={shortcutHelpOpen} onOpenChange={setShortcutHelpOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>검수 단축키</DialogTitle>
          </DialogHeader>
          <ul className="flex flex-col gap-1.5 text-sm">
            {REVIEW_SHORTCUTS.map((shortcut) => (
              <li
                key={shortcut.keys}
                className="flex items-center justify-between gap-3"
              >
                <span className="text-muted-foreground">{shortcut.label}</span>
                <kbd className="rounded border bg-muted px-1.5 py-0.5 font-mono text-xs">
                  {shortcut.keys}
                </kbd>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            입력창·버튼·대화상자에 포커스가 있거나 한글 조합 중에는 단축키가
            동작하지 않습니다.
          </p>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}

function RemovedCandidateRecoveryPanel({
  candidate,
  authoritativeCandidate,
  verificationPending,
  verificationError,
  pending,
  onRestore,
  onVerify,
}: {
  candidate: UnmatchedCandidate;
  authoritativeCandidate: UnmatchedCandidate | null;
  verificationPending: boolean;
  verificationError: string | null;
  pending: boolean;
  onRestore: (candidate: UnmatchedCandidate) => void;
  onVerify: () => void;
}) {
  const displayedCandidate = authoritativeCandidate ?? candidate;
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-primary/30 bg-primary/5 p-4">
      <div className="space-y-1">
        <p className="text-sm font-medium">
          {candidateReviewStateLabel(displayedCandidate.review_state)} 후보 복구
        </p>
        <p className="text-xs text-muted-foreground">
          복구하면 검수 대기로 돌아갑니다. 기존 확정 장소가 공유 중이면 장소는
          보존하고 이 후보의 연결만 해제합니다.
        </p>
      </div>
      {displayedCandidate.video_is_excluded ? (
        <p role="status" className="rounded-lg border border-warning/40 bg-warning/5 p-2 text-xs text-warning">
          이 후보의 출처 영상은 제외 상태입니다. 후보를 복구해도 영상 제외는 별도
          정책이므로 그대로 유지됩니다.
        </p>
      ) : null}
      <Button
        type="button"
        disabled={
          pending ||
          verificationPending ||
          authoritativeCandidate == null
        }
        onClick={() => {
          if (authoritativeCandidate) onRestore(authoritativeCandidate);
        }}
      >
        {pending ? (
          <Loader2Icon data-icon="inline-start" className="animate-spin" />
        ) : (
          <RotateCcwIcon data-icon="inline-start" />
        )}
        검수 대기로 복구
      </Button>
      {verificationPending ? (
        <p role="status" className="text-xs text-muted-foreground">
          최신 후보 상세와 복구 정보를 확인하는 중입니다.
        </p>
      ) : authoritativeCandidate == null ? (
        <div className="flex flex-wrap items-center gap-2">
          <p role="alert" className="text-xs text-destructive">
            {verificationError ??
              "최신 복구 정보를 신뢰할 수 없어 복구를 중지했습니다."}
          </p>
          <Button type="button" size="xs" variant="outline" onClick={onVerify}>
            최신 상세 다시 확인
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ReviewQueueSearch({
  value,
  onDebouncedChange,
}: {
  value: string;
  onDebouncedChange: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const [isComposing, setIsComposing] = useState(false);
  const previousValueRef = useRef(value);
  const pendingValueRef = useRef<string | null>(null);

  useEffect(() => {
    const previousValue = previousValueRef.current;
    const pendingValue = pendingValueRef.current;
    previousValueRef.current = value;
    pendingValueRef.current =
      value === previousValue ? pendingValue : null;
    setDraft((currentDraft) => {
      return reconcileReviewSearchDraft({
        draft: currentDraft,
        previousValue,
        value,
        pendingValue,
      }).draft;
    });
  }, [value]);

  useEffect(() => {
    if (isComposing) return;
    const normalized = draft.trim().slice(0, 255);
    if (normalized === value) return;
    const timer = window.setTimeout(() => {
      pendingValueRef.current = normalized;
      onDebouncedChange(normalized);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [draft, isComposing, onDebouncedChange, value]);

  return (
    <div className="relative">
      <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        aria-label="검수 후보 검색"
        className="pl-8"
        maxLength={255}
        placeholder="후보명·위치 힌트 검색"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onCompositionStart={() => setIsComposing(true)}
        onCompositionEnd={(event) => {
          setDraft(event.currentTarget.value);
          setIsComposing(false);
        }}
      />
    </div>
  );
}

function reprocessStageLabel(stage: ReprocessStage) {
  if (stage === "correction") return "교정부터";
  if (stage === "poi") return "POI 추출부터";
  return "자막 수집부터";
}

function groupDimLabel(dim: DestinationGroupDim) {
  if (dim === "channel") return "유튜버별";
  if (dim === "playlist") return "재생목록별";
  if (dim === "keyword") return "검색어별";
  return "전체";
}

function groupOptions(
  dim: DestinationGroupDim,
  facets: ReviewSourceFacets | undefined,
): { value: string; label: string; count: number }[] {
  if (!facets) return [];
  // T-187: 후보 provenance facet은 세 차원 모두 {value,label,candidate_count} 통일형.
  const items =
    dim === "channel"
      ? facets.channels
      : dim === "playlist"
        ? facets.playlists
        : dim === "keyword"
          ? facets.keywords
          : [];
  return items.map((item) => ({
    value: item.value,
    label: item.label,
    count: item.candidate_count,
  }));
}

function groupValueLabel(
  dim: DestinationGroupDim,
  value: string | null,
  facets: ReviewSourceFacets | undefined,
) {
  if (!value) return "";
  const option = groupOptions(dim, facets).find((opt) => opt.value === value);
  return option ? `${option.label} (${option.count})` : value;
}

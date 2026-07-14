import type {
  CandidateDetail,
  DestinationGroupDim,
  ReviewBulkFilterSnapshot,
  ReviewCandidateFilter,
  ReviewCandidateSort,
  ReviewCandidateStatus,
  ReviewGroundingStatus,
  ReviewQueueReason,
  ReviewSourceKind,
  UnmatchedCandidate,
} from "./api";

export const REVIEW_QUEUE_REASONS: readonly ReviewQueueReason[] = [
  "ungrounded",
  "name_mismatch",
  "region_mismatch",
  "source_conflict",
  "source_low_confidence",
  "source_uncertain",
  "ambiguous",
  "no_result",
  "vworld_unrefined_single",
  "foreign",
  "description_only",
  "visual_only",
  "provider_missing",
  "extraction_only",
];

export const REVIEW_SOURCE_KINDS: readonly ReviewSourceKind[] = [
  "transcript",
  "url_summary",
  "reconcile",
  "manual",
  "geocoding",
  "description",
  "visual",
];

export const REVIEW_GROUNDING_STATUSES: readonly ReviewGroundingStatus[] = [
  "verified_raw",
  "unverified",
  "missing",
  "not_applicable",
  "legacy_unknown",
];

export const MAX_DB_INTEGER_ID = 2_147_483_647;

export type ReviewListState = {
  groupDim: DestinationGroupDim;
  groupValue: string | null;
  query: string;
  sort: ReviewCandidateSort;
  isDomestic: boolean | null;
  queueReason: ReviewQueueReason | null;
  sourceKind: ReviewSourceKind | null;
  groundingStatus: ReviewGroundingStatus | null;
  status: Extract<ReviewCandidateStatus, "needs_review" | "removed">;
};

export const DEFAULT_REVIEW_LIST_STATE: ReviewListState = {
  groupDim: "none",
  groupValue: null,
  query: "",
  sort: "oldest",
  isDomestic: null,
  queueReason: null,
  sourceKind: null,
  groundingStatus: null,
  status: "needs_review",
};

/**
 * 검수 화면 표시 모드(T-187). filter가 아니라 뷰 concern이므로 `ReviewListState`나
 * `reviewListStateScopeKey`에 넣지 않는다 — 모드 전환이 큐 재조회·선택 초기화를
 * 유발하지 않아야 한다. URL `?mode=`가 단일 정본이고 기본은 처리 모드(triage)다.
 */
export type ReviewMode = "triage" | "table";
export const DEFAULT_REVIEW_MODE: ReviewMode = "triage";

export function parseReviewMode(params: SearchParamsReader): ReviewMode {
  return params.get("mode") === "table" ? "table" : "triage";
}

/** 기본값(triage)은 URL에서 생략해 링크를 깔끔하게 유지한다. */
export function writeReviewMode(
  current: URLSearchParams,
  mode: ReviewMode,
): URLSearchParams {
  const next = new URLSearchParams(current);
  if (mode === "table") next.set("mode", "table");
  else next.delete("mode");
  return next;
}

/** 객체/배열 identity와 무관하게 같은 검수 목록 조건인지 비교할 stable key다. */
export function reviewListStateScopeKey(state: ReviewListState): string {
  return JSON.stringify([
    state.groupDim,
    state.groupValue,
    state.query,
    state.sort,
    state.isDomestic,
    state.queueReason,
    state.sourceKind,
    state.groundingStatus,
    state.status,
  ]);
}

type SearchParamsReader = Pick<URLSearchParams, "get" | "getAll" | "has">;

const LIST_STATE_PARAMS = [
  "group",
  "group_value",
  "q",
  "sort",
  "is_domestic",
  "reason",
  "source_kind",
  "grounding",
  "status",
] as const;

function isGroupDim(
  value: string | null,
): value is Exclude<DestinationGroupDim, "none"> {
  return value === "channel" || value === "playlist" || value === "keyword";
}

function isQueueReason(value: string | null): value is ReviewQueueReason {
  return REVIEW_QUEUE_REASONS.some((reason) => reason === value);
}

function isSourceKind(value: string | null): value is ReviewSourceKind {
  return REVIEW_SOURCE_KINDS.some((sourceKind) => sourceKind === value);
}

function isGroundingStatus(
  value: string | null,
): value is ReviewGroundingStatus {
  return REVIEW_GROUNDING_STATUSES.some((status) => status === value);
}

export function hasReviewListStateParams(params: SearchParamsReader): boolean {
  return LIST_STATE_PARAMS.some((name) => params.has(name));
}

/** PostgreSQL INTEGER PK 범위의 양의 10진 정수만 후보 ID로 인정한다. */
export function parseReviewCandidateIdValue(raw: string): number | null {
  if (!/^[1-9]\d*$/.test(raw)) return null;
  const candidateId = Number(raw);
  return Number.isSafeInteger(candidateId) && candidateId <= MAX_DB_INTEGER_ID
    ? candidateId
    : null;
}

/** 유효 후보 딥링크가 중복되면 첫 값을 사용한다. */
export function parseReviewCandidateId(params: SearchParamsReader): number | null {
  for (const raw of params.getAll("candidate")) {
    const candidateId = parseReviewCandidateIdValue(raw);
    if (candidateId != null) return candidateId;
  }
  return null;
}

export function parseReviewListState(params: SearchParamsReader): ReviewListState {
  const rawGroupValue = params.get("group_value")?.trim() || null;
  const rawGroupDim = params.get("group");
  const groupDim = isGroupDim(rawGroupDim) ? rawGroupDim : "none";
  const domesticParam = params.get("is_domestic");
  const sortParam = params.get("sort");
  const statusParam = params.get("status");
  const reasonParam = params.get("reason");
  const sourceKindParam = params.get("source_kind");
  const groundingParam = params.get("grounding");

  return {
    groupDim,
    groupValue: groupDim === "none" ? null : rawGroupValue,
    query: (params.get("q") ?? "").trim().slice(0, 255),
    sort: sortParam === "newest" ? "newest" : "oldest",
    isDomestic:
      domesticParam === "true" ? true : domesticParam === "false" ? false : null,
    queueReason: isQueueReason(reasonParam) ? reasonParam : null,
    sourceKind: isSourceKind(sourceKindParam) ? sourceKindParam : null,
    groundingStatus: isGroundingStatus(groundingParam) ? groundingParam : null,
    // `ignored`는 T-183 링크 호환 입력으로만 받고, 삭제 후보까지 포함하는
    // `removed`를 URL 정본으로 쓴다.
    status:
      statusParam === "removed" || statusParam === "ignored"
        ? "removed"
        : "needs_review",
  };
}

export function writeReviewListState(
  current: URLSearchParams,
  state: ReviewListState,
): URLSearchParams {
  const next = new URLSearchParams(current);
  const candidateId = parseReviewCandidateId(current);
  for (const name of LIST_STATE_PARAMS) next.delete(name);
  next.delete("candidate");
  if (candidateId != null) next.set("candidate", String(candidateId));

  // sort는 기본값도 명시해 URL이 sessionStorage보다 항상 우선하는 표식으로 쓴다.
  next.set("sort", state.sort);
  if (state.groupDim !== "none") {
    next.set("group", state.groupDim);
    if (state.groupValue) next.set("group_value", state.groupValue);
  }
  const query = state.query.trim().slice(0, 255);
  if (query) next.set("q", query);
  if (state.isDomestic != null) {
    next.set("is_domestic", String(state.isDomestic));
  }
  if (state.queueReason) next.set("reason", state.queueReason);
  if (state.sourceKind) next.set("source_kind", state.sourceKind);
  if (state.groundingStatus) next.set("grounding", state.groundingStatus);
  if (state.status !== "needs_review") next.set("status", state.status);
  return next;
}

/** URL rerender를 기다리지 않고 연속 control patch를 합성하기 위한 순수 helper다. */
export function applyReviewListStatePatch(
  current: URLSearchParams,
  state: ReviewListState,
  patch: Partial<ReviewListState>,
): { params: URLSearchParams; state: ReviewListState } {
  const params = writeReviewListState(current, { ...state, ...patch });
  return { params, state: parseReviewListState(params) };
}

/**
 * debounce commit 응답이 늦게 도착해도 그 사이 입력한 최신 draft를 보존하고,
 * back/forward처럼 외부에서 value가 바뀐 경우에만 prop을 draft 정본으로 삼는다.
 */
export function reconcileReviewSearchDraft({
  draft,
  previousValue,
  value,
  pendingValue,
}: {
  draft: string;
  previousValue: string;
  value: string;
  pendingValue: string | null;
}): { draft: string; pendingValue: string | null } {
  if (value === previousValue) return { draft, pendingValue };
  if (value === pendingValue) return { draft, pendingValue: null };
  return { draft: value, pendingValue: null };
}

/** 후보/필터가 A→B→A로 돌아와도 과거 workflow command를 다시 활성화하지 않는다. */
export function isCurrentReviewWorkflow({
  commandCandidateId,
  commandQueueScope,
  commandEpoch,
  currentCandidateId,
  currentQueueScope,
  currentEpoch,
}: {
  commandCandidateId: number;
  commandQueueScope: string;
  commandEpoch: number;
  currentCandidateId: number | null;
  currentQueueScope: string;
  currentEpoch: number;
}): boolean {
  return (
    commandCandidateId === currentCandidateId &&
    commandQueueScope === currentQueueScope &&
    commandEpoch === currentEpoch
  );
}

export function reviewListStateToFilter(
  state: ReviewListState,
): ReviewCandidateFilter {
  return {
    channelId: state.groupDim === "channel" ? state.groupValue : null,
    playlistId: state.groupDim === "playlist" ? state.groupValue : null,
    keyword: state.groupDim === "keyword" ? state.groupValue : null,
    query: state.query || null,
    sort: state.sort,
    isDomestic: state.isDomestic,
    status: state.status,
    queueReason: state.queueReason,
    sourceKind: state.sourceKind,
    grounding: state.groundingStatus,
  };
}

export type ReviewBulkFilterOverrides = {
  /** undefined는 현재 목록값 유지, null은 국내외 전체, false는 해외만을 뜻한다. */
  isDomestic?: boolean | null;
  status?: "needs_review" | "removed";
};

/**
 * 현재 URL 목록 조건을 cursor/page/sort/deep-link와 분리된 bulk membership
 * snapshot으로 고정한다. optional 필드는 빈 문자열/null 대신 JSON에서 생략한다.
 */
export function reviewListStateToBulkFilter(
  state: ReviewListState,
  overrides: ReviewBulkFilterOverrides = {},
): ReviewBulkFilterSnapshot {
  const groupValue = state.groupValue?.trim() || undefined;
  const query = state.query.trim() || undefined;
  const isDomestic =
    overrides.isDomestic === undefined
      ? state.isDomestic
      : overrides.isDomestic;
  const status = overrides.status ?? state.status;

  return {
    ...(state.groupDim === "channel" && groupValue
      ? { channel_id: groupValue }
      : {}),
    ...(state.groupDim === "playlist" && groupValue
      ? { playlist_id: groupValue }
      : {}),
    ...(state.groupDim === "keyword" && groupValue
      ? { keyword: groupValue }
      : {}),
    ...(query ? { q: query } : {}),
    is_domestic: isDomestic,
    status,
    ...(state.queueReason ? { reason: state.queueReason } : {}),
    ...(state.sourceKind ? { source_kind: state.sourceKind } : {}),
    ...(state.groundingStatus
      ? { grounding: state.groundingStatus }
      : {}),
  };
}

/** 기존 교집합은 두되 reason=foreign을 자동 주입하지 않고 boolean 해외 조건을 쓴다. */
export function reviewListStateToForeignBulkFilter(
  state: ReviewListState,
): ReviewBulkFilterSnapshot<"needs_review"> {
  const filter = reviewListStateToBulkFilter(state, {
    isDomestic: false,
    status: "needs_review",
  });
  return { ...filter, status: "needs_review" };
}

export function reviewListStateHasFilters(state: ReviewListState): boolean {
  return (
    state.groupDim !== "none" ||
    Boolean(state.query) ||
    state.isDomestic != null ||
    state.queueReason != null ||
    state.sourceKind != null ||
    state.groundingStatus != null ||
    state.status !== "needs_review"
  );
}

export function isReviewCandidateActionable(
  candidate: UnmatchedCandidate,
): boolean {
  return candidate.review_state === "needs_review";
}

export function reviewCandidateMatchesStatus(
  candidate: UnmatchedCandidate,
  status: ReviewListState["status"],
): boolean {
  if (status === "removed") {
    return (
      candidate.review_state === "ignored" ||
      candidate.review_state === "deleted"
    );
  }
  return candidate.review_state === "needs_review";
}

// 서버 PostgreSQL ILIKE의 locale별 모든 동작을 JS에서 복제할 수는 없지만,
// 동일 문자열 self-search는 Unicode 소문자화 뒤 반드시 포함되도록 계약한다.
function containsFolded(value: string | null, query: string): boolean {
  return value?.toLowerCase().includes(query) ?? false;
}

/** 상세 단건이 현재 서버 filter에 속하는지 목록과 같은 scalar 의미로 판정한다. */
export function candidateMatchesReviewListState(
  detail: CandidateDetail,
  state: ReviewListState,
): boolean {
  const item = detail.list_item;
  if (!reviewCandidateMatchesStatus(item, state.status)) return false;
  if (state.isDomestic != null && item.is_domestic !== state.isDomestic) {
    return false;
  }
  if (state.queueReason && item.queue_reason !== state.queueReason) return false;
  if (state.sourceKind && item.source_kind !== state.sourceKind) return false;
  if (
    state.groundingStatus &&
    item.grounding_status !== state.groundingStatus
  ) {
    return false;
  }

  const query = state.query.trim().toLowerCase();
  if (
    query &&
    !containsFolded(item.ai_place_name, query) &&
    !containsFolded(item.location_hint, query)
  ) {
    return false;
  }

  if (state.groupDim === "channel") {
    if (!state.groupValue) return true;
    return (
      detail.candidate.source_channel_id === state.groupValue ||
      detail.video?.channel_id === state.groupValue
    );
  }
  if (state.groupDim === "playlist") {
    if (!state.groupValue) return true;
    return detail.candidate.source_playlist_id === state.groupValue;
  }
  if (state.groupDim === "keyword") {
    if (!state.groupValue) return true;
    return detail.video?.source_search_query === state.groupValue;
  }
  return true;
}

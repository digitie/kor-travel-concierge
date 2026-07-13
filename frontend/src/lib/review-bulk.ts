import {
  REVIEW_BULK_CANDIDATE_ID_MAX,
  REVIEW_BULK_CHUNK_SIZE,
  REVIEW_BULK_FILTER_MAX,
  REVIEW_BULK_SELECTION_MAX,
  type ReviewBulkAction,
  type ReviewBulkExecuteInput,
  type ReviewBulkExecuteResult,
  type ReviewBulkFilterSnapshot,
  type ReviewBulkItemIssue,
  type ReviewBulkPreview,
  type ReviewBulkPreviewInput,
  type ReviewBulkPreviewInputForAction,
  type ReviewBulkScope,
  type ReviewBulkScopeForAction,
} from "./api";

export type ReviewBulkWorkflowStatus =
  | "idle"
  | "previewing"
  | "confirm"
  | "executing"
  | "completed"
  | "partial"
  | "expired"
  | "error";

export type ReviewBulkDraftForAction<Action extends ReviewBulkAction> =
  ReviewBulkPreviewInputForAction<Action> & {
    /** action과 canonical scope를 함께 묶은 지연 응답 차단 key다. */
    fenceKey: string;
  };

export type ReviewBulkDraft = ReviewBulkDraftForAction<ReviewBulkAction>;

export type ReviewBulkProgress = {
  total: number;
  processed: number;
  succeeded: number;
  conflicts: ReviewBulkItemIssue[];
  failed: ReviewBulkItemIssue[];
  remaining: number;
  /** 다음 chunk가 시작할 서버 cursor다. 첫 chunk는 null이다. */
  cursor: string | null;
};

/** 확인 token/request/cursor를 제외하고 사용자에게 공개해도 되는 누적 결과다. */
export type ReviewBulkProgressSummary = {
  total: number;
  processed: number;
  succeeded: number;
  conflicts: number;
  failed: number;
  remaining: number;
};

export type ReviewBulkChunkRequest = {
  requestId: string;
  cursor: string | null;
};

export type ReviewBulkPreviewSummary = Omit<
  ReviewBulkPreview,
  "confirmation_token"
>;

export type ReviewBulkIdleState = {
  status: "idle";
  sequence: number;
  fenceKey: string | null;
};

type ReviewBulkActiveBase = {
  sequence: number;
  fenceKey: string;
  draft: ReviewBulkDraft;
};

export type ReviewBulkPreviewingState = ReviewBulkActiveBase & {
  status: "previewing";
};

export type ReviewBulkConfirmState = ReviewBulkActiveBase & {
  status: "confirm";
  preview: ReviewBulkPreview;
};

export type ReviewBulkExecutingState = ReviewBulkActiveBase & {
  status: "executing";
  preview: ReviewBulkPreview;
  progress: ReviewBulkProgress;
  /** null이면 다음 chunk의 새 request_id를 발급할 차례다. */
  request: ReviewBulkChunkRequest | null;
};

type ReviewBulkSettledBase = ReviewBulkActiveBase & {
  preview: ReviewBulkPreviewSummary;
  progress: ReviewBulkProgress;
};

export type ReviewBulkCompletedState =
  | (ReviewBulkSettledBase & { status: "completed" })
  | (ReviewBulkSettledBase & { status: "partial" });

export type ReviewBulkExpiredState = ReviewBulkActiveBase & {
  status: "expired";
  message: string;
  preview?: ReviewBulkPreviewSummary;
  /** 실행 중 410이면 bearer 자료 없는, 서버 응답으로 확인된 누적 요약만 남긴다. */
  progress?: ReviewBulkProgressSummary;
};

export type ReviewBulkPreviewErrorState = ReviewBulkActiveBase & {
  status: "error";
  phase: "preview";
  retryable: boolean;
  message: string;
};

/** response-loss 가능성이 있어 같은 chunk receipt를 재요청할 수 있는 유일한 오류다. */
export type ReviewBulkRetryableExecuteErrorState = ReviewBulkActiveBase & {
  status: "error";
  phase: "execute";
  retryable: true;
  message: string;
  preview: ReviewBulkPreview;
  progress: ReviewBulkProgress;
  /** response-loss 재시도에서 cursor와 request_id를 절대 새로 만들지 않는다. */
  request: ReviewBulkChunkRequest;
};

/** 계약/fatal 오류는 bearer 재시도 자료를 폐기하고 token-free 누적 요약만 남긴다. */
export type ReviewBulkTerminalExecuteErrorState = ReviewBulkActiveBase & {
  status: "error";
  phase: "terminal";
  retryable: false;
  message: string;
  terminalKind: "fatal" | "contract" | "stale_conflict";
  /** 이전 receipt로 확인된 누적 결과만 보존하며 bearer 자료는 포함하지 않는다. */
  progress: ReviewBulkProgressSummary;
};

export type ReviewBulkExecuteErrorState =
  | ReviewBulkRetryableExecuteErrorState
  | ReviewBulkTerminalExecuteErrorState;

export type ReviewBulkState =
  | ReviewBulkIdleState
  | ReviewBulkPreviewingState
  | ReviewBulkConfirmState
  | ReviewBulkExecutingState
  | ReviewBulkCompletedState
  | ReviewBulkExpiredState
  | ReviewBulkPreviewErrorState
  | ReviewBulkExecuteErrorState;

export type ReviewBulkFenceRef = {
  sequence: number;
  fenceKey: string;
};

export type ReviewBulkConfirmationRef = ReviewBulkFenceRef & {
  operationId: string;
  expiresAt: string;
};

export type ReviewBulkExecuteRef = ReviewBulkFenceRef & {
  requestId: string;
  cursor: string | null;
};

export type ReviewBulkFailure = {
  kind: "retryable" | "expired" | "stale_conflict" | "fatal";
  message: string;
};

export const INITIAL_REVIEW_BULK_STATE: ReviewBulkIdleState = {
  status: "idle",
  sequence: 0,
  fenceKey: null,
};

const REVIEW_BULK_CONFIRMATION_TIMER_MAX_DELAY_MS = 2_147_483_647;
const REVIEW_BULK_CONFIRMATION_TOKEN_MAX_LENGTH = 512;
const REVIEW_BULK_UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const REVIEW_BULK_TOKEN_SECRET_PATTERN = /^[A-Za-z0-9_-]+$/;

function optionalFilterValue(value: string | undefined): string | undefined {
  const normalized = value?.trim();
  return normalized || undefined;
}

function canonicalReviewBulkScope(scope: ReviewBulkScope): ReviewBulkScope {
  if (scope.kind === "selection") {
    const candidateIds = [...new Set(scope.candidateIds)];
    if (
      candidateIds.length === 0 ||
      candidateIds.length > REVIEW_BULK_SELECTION_MAX ||
      candidateIds.some(
        (candidateId) =>
          !Number.isSafeInteger(candidateId) ||
          candidateId <= 0 ||
          candidateId > REVIEW_BULK_CANDIDATE_ID_MAX,
      )
    ) {
      throw new Error(
        `일괄 검수 후보는 양의 정수 ID ${REVIEW_BULK_SELECTION_MAX}개 이하이어야 합니다.`,
      );
    }
    candidateIds.sort((a, b) => a - b);
    return { kind: "selection", candidateIds };
  }

  const filter = scope.filter;
  const canonicalFilter: ReviewBulkFilterSnapshot = {
    ...(optionalFilterValue(filter.channel_id)
      ? { channel_id: optionalFilterValue(filter.channel_id) }
      : {}),
    ...(optionalFilterValue(filter.playlist_id)
      ? { playlist_id: optionalFilterValue(filter.playlist_id) }
      : {}),
    ...(optionalFilterValue(filter.keyword)
      ? { keyword: optionalFilterValue(filter.keyword) }
      : {}),
    ...(optionalFilterValue(filter.q)
      ? { q: optionalFilterValue(filter.q) }
      : {}),
    is_domestic:
      typeof filter.is_domestic === "boolean" ? filter.is_domestic : null,
    status: filter.status ?? "needs_review",
    ...(filter.reason ? { reason: filter.reason } : {}),
    ...(filter.source_kind ? { source_kind: filter.source_kind } : {}),
    ...(filter.grounding ? { grounding: filter.grounding } : {}),
  };
  return canonicalFilter.status === "removed"
    ? {
        kind: "filter",
        filter: { ...canonicalFilter, status: "removed" },
      }
    : {
        kind: "filter",
        filter: { ...canonicalFilter, status: "needs_review" },
      };
}

/** 배열 순서/중복/object identity와 무관한 bulk membership key다. */
export function reviewBulkScopeKey(scope: ReviewBulkScope): string {
  const canonical = canonicalReviewBulkScope(scope);
  if (canonical.kind === "selection") {
    return JSON.stringify(["selection", canonical.candidateIds]);
  }
  const filter = canonical.filter;
  return JSON.stringify([
    "filter",
    filter.channel_id ?? null,
    filter.playlist_id ?? null,
    filter.keyword ?? null,
    filter.q ?? null,
    filter.is_domestic,
    filter.status,
    filter.reason ?? null,
    filter.source_kind ?? null,
    filter.grounding ?? null,
  ]);
}

export function createReviewBulkDraft<Action extends ReviewBulkAction>(
  action: Action,
  scope: NoInfer<ReviewBulkScopeForAction<Action>>,
): ReviewBulkDraftForAction<Action>;
export function createReviewBulkDraft(
  action: ReviewBulkAction,
  scope: ReviewBulkScope,
): ReviewBulkDraft {
  const canonicalScope = canonicalReviewBulkScope(scope);
  if (
    canonicalScope.kind === "filter" &&
    ((action === "reopen" && canonicalScope.filter.status !== "removed") ||
      (action !== "reopen" &&
        canonicalScope.filter.status !== "needs_review"))
  ) {
    throw new Error("일괄 검수 action과 filter 상태가 일치하지 않습니다.");
  }
  return {
    action,
    scope: canonicalScope,
    fenceKey: JSON.stringify([action, reviewBulkScopeKey(canonicalScope)]),
  } as ReviewBulkDraft;
}

function previewSummary(preview: ReviewBulkPreview): ReviewBulkPreviewSummary {
  return {
    operation_id: preview.operation_id,
    expires_at: preview.expires_at,
    total: preview.total,
    chunk_size: preview.chunk_size,
  };
}

export function summarizeReviewBulkProgress(
  progress: ReviewBulkProgress,
): ReviewBulkProgressSummary {
  return {
    total: progress.total,
    processed: progress.processed,
    succeeded: progress.succeeded,
    conflicts: progress.conflicts.length,
    failed: progress.failed.length,
    remaining: progress.remaining,
  };
}

function previewExpired(preview: ReviewBulkPreview, nowMs: number): boolean {
  const expiresAt = Date.parse(preview.expires_at);
  return !Number.isFinite(expiresAt) || expiresAt <= nowMs;
}

function validUuid(value: string): boolean {
  return REVIEW_BULK_UUID_PATTERN.test(value);
}

function validConfirmationToken(token: string, operationId: string): boolean {
  if (
    token.length === 0 ||
    token.length > REVIEW_BULK_CONFIRMATION_TOKEN_MAX_LENGTH ||
    token !== token.trim()
  ) {
    return false;
  }
  const [version, tokenOperationId, secret, ...extra] = token.split(".");
  return (
    extra.length === 0 &&
    version === "rbulk1" &&
    tokenOperationId?.toLowerCase() === operationId.toLowerCase() &&
    typeof secret === "string" &&
    REVIEW_BULK_TOKEN_SECRET_PATTERN.test(secret)
  );
}

function validPreview(
  preview: ReviewBulkPreview,
  scope: ReviewBulkScope,
): boolean {
  // selection은 client가 canonical 개수를 알고 있으므로 응답과 대조한다. filter의 exact
  // total은 같은 대상을 다시 조회하지 않고 독립 검증할 수 없으므로 여기서는 서버 안전
  // 상한만 확인하고, 멤버십 정확성은 backend ASGI/PostgreSQL 계약 테스트를 정본으로 둔다.
  return (
    preview != null &&
    typeof preview === "object" &&
    typeof preview.operation_id === "string" &&
    validUuid(preview.operation_id) &&
    typeof preview.confirmation_token === "string" &&
    validConfirmationToken(
      preview.confirmation_token,
      preview.operation_id,
    ) &&
    typeof preview.expires_at === "string" &&
    Number.isSafeInteger(preview.total) &&
    preview.total >= 0 &&
    preview.total <= REVIEW_BULK_FILTER_MAX &&
    (scope.kind !== "selection" ||
      preview.total === scope.candidateIds.length) &&
    Number.isSafeInteger(preview.chunk_size) &&
    preview.chunk_size === REVIEW_BULK_CHUNK_SIZE &&
    Number.isFinite(Date.parse(preview.expires_at))
  );
}

function validRequestId(requestId: string): boolean {
  return validUuid(requestId);
}

function sameFence(
  state: ReviewBulkState,
  ref: ReviewBulkFenceRef,
): boolean {
  return (
    state.sequence === ref.sequence &&
    state.fenceKey != null &&
    state.fenceKey === ref.fenceKey
  );
}

function sameCursor(left: string | null, right: string | null): boolean {
  return left === right;
}

function expiredState(
  state: ReviewBulkConfirmState | ReviewBulkExecutingState,
  message: string,
): ReviewBulkExpiredState {
  return {
    status: "expired",
    sequence: state.sequence,
    fenceKey: state.fenceKey,
    draft: state.draft,
    message,
    preview: previewSummary(state.preview),
    ...(state.status === "executing"
      ? { progress: summarizeReviewBulkProgress(state.progress) }
      : {}),
  };
}

export function reviewBulkConfirmationRef(
  state: ReviewBulkState,
): ReviewBulkConfirmationRef | null {
  if (state.status !== "confirm") return null;
  return {
    sequence: state.sequence,
    fenceKey: state.fenceKey,
    operationId: state.preview.operation_id,
    expiresAt: state.preview.expires_at,
  };
}

/** 브라우저 setTimeout의 signed 32-bit 상한을 넘지 않는 다음 확인 시각이다. */
export function reviewBulkConfirmationDelayMs(
  expiresAt: string,
  nowMs = Date.now(),
): number {
  const delay = Date.parse(expiresAt) - nowMs;
  if (!Number.isFinite(delay)) return 0;
  return Math.min(
    Math.max(0, delay),
    REVIEW_BULK_CONFIRMATION_TIMER_MAX_DELAY_MS,
  );
}

/** timer가 붙잡은 세대의 confirm만 만료시키고 bearer token을 폐기한다. */
export function expireReviewBulkConfirmation(
  state: ReviewBulkState,
  ref: ReviewBulkConfirmationRef,
  nowMs = Date.now(),
): ReviewBulkState {
  if (
    state.status !== "confirm" ||
    !sameFence(state, ref) ||
    state.preview.operation_id !== ref.operationId ||
    state.preview.expires_at !== ref.expiresAt ||
    !previewExpired(state.preview, nowMs)
  ) {
    return state;
  }
  return expiredState(
    state,
    "일괄 검수 확인 시간이 만료되었습니다. 범위를 다시 확인해 주세요.",
  );
}

/** 현재 scope/action이 달라지면 실행 중 응답까지 포함해 이전 세대를 폐기한다. */
export function fenceReviewBulkScope(
  state: ReviewBulkState,
  draft: ReviewBulkDraft,
): ReviewBulkState {
  if (state.fenceKey === draft.fenceKey) return state;
  return {
    status: "idle",
    sequence: state.sequence + 1,
    fenceKey: draft.fenceKey,
  };
}

export function beginReviewBulkPreview(
  state: ReviewBulkState,
  draft: ReviewBulkDraft,
): ReviewBulkState {
  if (
    state.status === "previewing" &&
    state.fenceKey === draft.fenceKey
  ) {
    return state;
  }
  return {
    status: "previewing",
    sequence: state.sequence + 1,
    fenceKey: draft.fenceKey,
    draft,
  };
}

export function reviewBulkPreviewRef(
  state: ReviewBulkState,
): ReviewBulkFenceRef | null {
  return state.status === "previewing"
    ? { sequence: state.sequence, fenceKey: state.fenceKey }
    : null;
}

export function reviewBulkPreviewRequest(
  state: ReviewBulkState,
): ReviewBulkPreviewInput | null {
  if (state.status !== "previewing") return null;
  if (state.draft.action === "reopen") {
    return { action: "reopen", scope: state.draft.scope };
  }
  if (state.draft.action === "delete") {
    return { action: "delete", scope: state.draft.scope };
  }
  return { action: "ignore", scope: state.draft.scope };
}

export function receiveReviewBulkPreview(
  state: ReviewBulkState,
  ref: ReviewBulkFenceRef,
  preview: ReviewBulkPreview,
  nowMs = Date.now(),
): ReviewBulkState {
  if (state.status !== "previewing" || !sameFence(state, ref)) return state;
  if (!validPreview(preview, state.draft.scope)) {
    return {
      status: "error",
      phase: "preview",
      retryable: false,
      message: "일괄 검수 preview 응답 계약이 올바르지 않습니다.",
      sequence: state.sequence,
      fenceKey: state.fenceKey,
      draft: state.draft,
    };
  }
  if (previewExpired(preview, nowMs)) {
    return {
      status: "expired",
      sequence: state.sequence,
      fenceKey: state.fenceKey,
      draft: state.draft,
      message: "일괄 검수 확인 시간이 만료되었습니다. 범위를 다시 확인해 주세요.",
      preview: previewSummary(preview),
    };
  }
  return {
    status: "confirm",
    sequence: state.sequence,
    fenceKey: state.fenceKey,
    draft: state.draft,
    preview: { ...preview },
  };
}

export function failReviewBulkPreview(
  state: ReviewBulkState,
  ref: ReviewBulkFenceRef,
  failure: ReviewBulkFailure,
): ReviewBulkState {
  if (state.status !== "previewing" || !sameFence(state, ref)) return state;
  if (failure.kind === "expired") {
    return {
      status: "expired",
      sequence: state.sequence,
      fenceKey: state.fenceKey,
      draft: state.draft,
      message: failure.message,
    };
  }
  return {
    status: "error",
    phase: "preview",
    retryable: failure.kind === "retryable",
    message: failure.message,
    sequence: state.sequence,
    fenceKey: state.fenceKey,
    draft: state.draft,
  };
}

export function confirmReviewBulk(
  state: ReviewBulkState,
  requestId: string,
  nowMs = Date.now(),
): ReviewBulkState {
  // confirm 버튼 연타는 첫 request가 실행 상태를 점유하므로 그대로 무시된다.
  if (state.status !== "confirm") return state;
  if (!validRequestId(requestId)) {
    throw new Error("일괄 검수 request_id는 UUID여야 합니다.");
  }
  if (previewExpired(state.preview, nowMs)) {
    return expiredState(
      state,
      "일괄 검수 확인 시간이 만료되었습니다. 범위를 다시 확인해 주세요.",
    );
  }
  return {
    status: "executing",
    sequence: state.sequence,
    fenceKey: state.fenceKey,
    draft: state.draft,
    preview: state.preview,
    progress: {
      total: state.preview.total,
      processed: 0,
      succeeded: 0,
      conflicts: [],
      failed: [],
      remaining: state.preview.total,
      cursor: null,
    },
    request: { requestId, cursor: null },
  };
}

export function beginNextReviewBulkChunk(
  state: ReviewBulkState,
  requestId: string,
  _nowMs = Date.now(),
): ReviewBulkState {
  void _nowMs;
  if (state.status !== "executing" || state.request != null) return state;
  if (!validRequestId(requestId)) {
    throw new Error("일괄 검수 request_id는 UUID여야 합니다.");
  }
  // expires_at은 최초 시작 전 확인 시각이다. 시작된 operation은 오래 걸려도
  // client가 중단하지 않고, 서버가 명시적으로 410을 줄 때만 expired로 전이한다.
  return {
    ...state,
    request: { requestId, cursor: state.progress.cursor },
  };
}

export function reviewBulkExecuteRef(
  state: ReviewBulkState,
): ReviewBulkExecuteRef | null {
  if (state.status !== "executing" || state.request == null) return null;
  return {
    sequence: state.sequence,
    fenceKey: state.fenceKey,
    requestId: state.request.requestId,
    cursor: state.request.cursor,
  };
}

export function reviewBulkExecuteRequest(
  state: ReviewBulkState,
): ReviewBulkExecuteInput | null {
  if (state.status !== "executing" || state.request == null) return null;
  return {
    operationId: state.preview.operation_id,
    confirmationToken: state.preview.confirmation_token,
    cursor: state.request.cursor,
    requestId: state.request.requestId,
  };
}

function sameExecuteRequest(
  state: ReviewBulkState,
  ref: ReviewBulkExecuteRef,
): state is ReviewBulkExecutingState & { request: ReviewBulkChunkRequest } {
  return (
    state.status === "executing" &&
    state.request != null &&
    sameFence(state, ref) &&
    state.request.requestId === ref.requestId &&
    sameCursor(state.request.cursor, ref.cursor)
  );
}

function executeContractError(
  state: ReviewBulkExecutingState & { request: ReviewBulkChunkRequest },
  message: string,
): ReviewBulkTerminalExecuteErrorState {
  return {
    status: "error",
    phase: "terminal",
    retryable: false,
    message,
    terminalKind: "contract",
    progress: summarizeReviewBulkProgress(state.progress),
    sequence: state.sequence,
    fenceKey: state.fenceKey,
    draft: state.draft,
  };
}

function nonNegativeInteger(value: number): boolean {
  return Number.isSafeInteger(value) && value >= 0;
}

function validReviewBulkIssue(issue: ReviewBulkItemIssue): boolean {
  return (
    issue != null &&
    typeof issue === "object" &&
    Number.isSafeInteger(issue.candidate_id) &&
    issue.candidate_id > 0 &&
    issue.candidate_id <= REVIEW_BULK_CANDIDATE_ID_MAX &&
    typeof issue.code === "string" &&
    issue.code.trim().length > 0 &&
    typeof issue.message === "string" &&
    issue.message.trim().length > 0
  );
}

export function receiveReviewBulkExecution(
  state: ReviewBulkState,
  ref: ReviewBulkExecuteRef,
  result: ReviewBulkExecuteResult,
): ReviewBulkState {
  // 다른 세대, 이미 반영한 receipt, 이전 chunk replay는 모두 무시한다.
  if (!sameExecuteRequest(state, ref)) return state;
  if (
    result == null ||
    typeof result !== "object" ||
    typeof result.operation_id !== "string" ||
    typeof result.request_id !== "string" ||
    result.operation_id !== state.preview.operation_id ||
    result.request_id !== ref.requestId ||
    !nonNegativeInteger(result.processed) ||
    !nonNegativeInteger(result.succeeded) ||
    result.succeeded > result.processed ||
    result.processed > state.preview.chunk_size ||
    !nonNegativeInteger(result.remaining) ||
    !Array.isArray(result.conflicts) ||
    !Array.isArray(result.failed) ||
    typeof result.complete !== "boolean" ||
    (result.next_cursor !== null &&
      (typeof result.next_cursor !== "string" ||
        result.next_cursor.trim().length === 0)) ||
    !result.conflicts.every(validReviewBulkIssue) ||
    !result.failed.every(validReviewBulkIssue) ||
    result.processed !==
      result.succeeded + result.conflicts.length + result.failed.length
  ) {
    return executeContractError(
      state,
      "일괄 검수 chunk 응답 계약이 올바르지 않습니다.",
    );
  }
  if (
    (!result.complete &&
      (result.remaining === 0 ||
        !result.next_cursor ||
        result.next_cursor === ref.cursor ||
        result.processed === 0)) ||
    (result.complete && (result.remaining !== 0 || result.next_cursor != null))
  ) {
    return executeContractError(
      state,
      "일괄 검수 chunk가 다음 진행 위치를 제공하지 않았습니다.",
    );
  }

  const progress: ReviewBulkProgress = {
    total: state.progress.total,
    processed: state.progress.processed + result.processed,
    succeeded: state.progress.succeeded + result.succeeded,
    conflicts: [...state.progress.conflicts, ...result.conflicts],
    failed: [...state.progress.failed, ...result.failed],
    remaining: result.remaining,
    cursor: result.next_cursor,
  };
  if (progress.processed + progress.remaining !== progress.total) {
    return executeContractError(
      state,
      "일괄 검수 누적 처리 건수와 남은 건수가 preview 범위와 다릅니다.",
    );
  }
  if (result.complete) {
    const partial =
      progress.conflicts.length > 0 ||
      progress.failed.length > 0 ||
      progress.succeeded < progress.processed;
    return {
      status: partial ? "partial" : "completed",
      sequence: state.sequence,
      fenceKey: state.fenceKey,
      draft: state.draft,
      preview: previewSummary(state.preview),
      progress,
    };
  }
  return {
    ...state,
    progress,
    request: null,
  };
}

export function failReviewBulkExecution(
  state: ReviewBulkState,
  ref: ReviewBulkExecuteRef,
  failure: ReviewBulkFailure,
): ReviewBulkState {
  if (!sameExecuteRequest(state, ref)) return state;
  if (failure.kind === "expired") {
    return expiredState(state, failure.message);
  }
  if (failure.kind === "retryable") {
    return {
      status: "error",
      phase: "execute",
      retryable: true,
      message: failure.message,
      sequence: state.sequence,
      fenceKey: state.fenceKey,
      draft: state.draft,
      preview: state.preview,
      progress: state.progress,
      request: state.request,
    };
  }
  return {
    status: "error",
    phase: "terminal",
    retryable: false,
    message: failure.message,
    terminalKind:
      failure.kind === "stale_conflict" ? "stale_conflict" : "fatal",
    progress: summarizeReviewBulkProgress(state.progress),
    sequence: state.sequence,
    fenceKey: state.fenceKey,
    draft: state.draft,
  };
}

export function retryReviewBulk(
  state: ReviewBulkState,
  _nowMs = Date.now(),
): ReviewBulkState {
  void _nowMs;
  if (state.status !== "error" || !state.retryable) return state;
  if (state.phase === "preview") {
    return {
      status: "previewing",
      sequence: state.sequence + 1,
      fenceKey: state.fenceKey,
      draft: state.draft,
    };
  }
  if (state.phase !== "execute") return state;
  // response-loss 가능성이 있으므로 같은 request_id와 cursor를 그대로 재전송한다.
  return {
    status: "executing",
    sequence: state.sequence,
    fenceKey: state.fenceKey,
    draft: state.draft,
    preview: state.preview,
    progress: state.progress,
    request: state.request,
  };
}

/** token/operation을 저장소나 URL로 옮기지 않고 현재 메모리 상태에서 폐기한다. */
export function resetReviewBulk(state: ReviewBulkState): ReviewBulkIdleState {
  return {
    status: "idle",
    sequence: state.sequence + 1,
    fenceKey: state.fenceKey,
  };
}

export function cancelReviewBulk(state: ReviewBulkState): ReviewBulkIdleState {
  return resetReviewBulk(state);
}

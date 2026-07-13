import type {
  CandidateDetail,
  CandidateReviewState,
  CandidateUndoDescriptor,
  DeleteCandidateResult,
  ResolveCandidateInput,
} from "./api";
import type { CandidateDetailRevalidation } from "./review-candidate-cache";

export type ReviewUndoAction = ResolveCandidateInput["action"] | "delete";

export type ReviewUndoEntry = {
  generation: number;
  descriptor: CandidateUndoDescriptor;
  candidateName: string;
  action: ReviewUndoAction;
  expectedReviewState: CandidateReviewState;
};

export type ReviewUndoState = {
  generation: number;
  current: ReviewUndoEntry | null;
};

export const INITIAL_REVIEW_UNDO_STATE: ReviewUndoState = {
  generation: 0,
  current: null,
};

export type ReviewActionSuccess = {
  candidateId: number;
  candidateName: string;
  action: ReviewUndoAction;
  reviewState: CandidateReviewState;
  undo?: CandidateUndoDescriptor | null;
  processedCount?: number;
};

export type ReviewUndoHandoff = ReviewActionSuccess & {
  clientOperationId: string;
};

export const REVIEW_UNDO_HANDOFF_STORAGE_KEY = "ktc.review.undo-handoff.v2";
export const REVIEW_UNDO_HANDOFF_TTL_MS = 5 * 60 * 1_000;
export const CANDIDATE_OPERATION_MARKER_DELAYS_MS = [150, 350, 750] as const;

const REVIEW_STATES = new Set<CandidateReviewState>([
  "needs_review",
  "ignored",
  "deleted",
  "matched",
  "user_corrected",
]);
const REVIEW_ACTIONS = new Set<ReviewUndoAction>([
  "match_existing",
  "create_place",
  "ignore",
  "delete",
]);
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** 모바일 상세 route의 마지막 단건 결과를 검수 큐에 한 번만 넘기는 JSON 계약이다. */
export function serializeReviewUndoHandoff(
  success: ReviewUndoHandoff,
  now = Date.now(),
): string {
  const { clientOperationId, ...actionSuccess } = success;
  return JSON.stringify({
    version: 2,
    created_at: new Date(now).toISOString(),
    client_operation_id: clientOperationId,
    ...actionSuccess,
  });
}

export function parseReviewUndoHandoff(
  value: string | null,
  now = Date.now(),
): ReviewUndoHandoff | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    const undo = parsed.undo as Record<string, unknown> | null | undefined;
    if (
      parsed.version !== 2 ||
      typeof parsed.created_at !== "string" ||
      !Number.isFinite(Date.parse(parsed.created_at)) ||
      Date.parse(parsed.created_at) > now + 30_000 ||
      now - Date.parse(parsed.created_at) > REVIEW_UNDO_HANDOFF_TTL_MS ||
      typeof parsed.client_operation_id !== "string" ||
      !UUID_PATTERN.test(parsed.client_operation_id) ||
      typeof parsed.candidateId !== "number" ||
      !Number.isSafeInteger(parsed.candidateId) ||
      parsed.candidateId <= 0 ||
      typeof parsed.candidateName !== "string" ||
      !REVIEW_ACTIONS.has(parsed.action as ReviewUndoAction) ||
      !REVIEW_STATES.has(parsed.reviewState as CandidateReviewState) ||
      !undo ||
      undo.candidate_id !== parsed.candidateId ||
      typeof undo.token !== "string" ||
      undo.token.length === 0
    ) {
      return null;
    }
    return {
      candidateId: parsed.candidateId,
      candidateName: parsed.candidateName,
      action: parsed.action as ReviewUndoAction,
      reviewState: parsed.reviewState as CandidateReviewState,
      clientOperationId: parsed.client_operation_id,
      undo: {
        candidate_id: undo.candidate_id as number,
        token: undo.token,
      },
    };
  } catch {
    return null;
  }
}

export type ConfirmedCandidateDelete = {
  stateRevision: number;
  undo: CandidateUndoDescriptor;
};

/** DELETE의 exact detail이 후보/list 양쪽에서 같은 persisted operation을 가리키는지 확인한다. */
export function confirmCandidateDeleteDetail({
  detail,
  candidateId,
  expectedRevision,
  clientOperationId,
}: {
  detail: CandidateDetail;
  candidateId: number;
  expectedRevision: number;
  clientOperationId: string;
}): ConfirmedCandidateDelete | null {
  const listItem = detail.list_item;
  const candidate = detail.candidate;
  const listUndo = listItem.undo;
  const candidateUndo = candidate.undo;
  if (
    listItem.id !== candidateId ||
    candidate.id !== candidateId ||
    listItem.review_state !== "deleted" ||
    candidate.review_state !== "deleted" ||
    listItem.state_revision <= expectedRevision ||
    candidate.state_revision !== listItem.state_revision ||
    listItem.last_client_operation_id !== clientOperationId ||
    candidate.last_client_operation_id !== clientOperationId ||
    !listUndo ||
    !candidateUndo ||
    listUndo.candidate_id !== candidateId ||
    candidateUndo.candidate_id !== candidateId ||
    listUndo.token.length === 0 ||
    candidateUndo.token !== listUndo.token
  ) {
    return null;
  }
  return { stateRevision: listItem.state_revision, undo: listUndo };
}

/** DELETE 200의 반사값과 persisted exact detail을 모두 만족해야 성공으로 본다. */
export function deleteResponseMatchesConfirmedDetail({
  response,
  confirmed,
  candidateId,
  clientOperationId,
}: {
  response: DeleteCandidateResult | null;
  confirmed: ConfirmedCandidateDelete;
  candidateId: number;
  clientOperationId: string;
}): boolean {
  if (!response || !response.undo) return false;
  return Boolean(
    response.deleted === true &&
      response.client_operation_id === clientOperationId &&
      response.id === candidateId &&
      response.review_state === "deleted" &&
      response.state_revision === confirmed.stateRevision &&
      response.undo.candidate_id === candidateId &&
      response.undo.token.length > 0 &&
      response.undo.token === confirmed.undo.token,
  );
}

function operationMarkerPending(
  detail: CandidateDetail,
  candidateId: number,
  expectedReviewState: CandidateReviewState,
): boolean {
  // forward mutation이 적용되지 않은 원 상태다. needs_review 자체를 기다리면
  // "요청 미적용"을 finalizer 지연으로 오인해 불필요한 backoff를 수행한다.
  if (expectedReviewState === "needs_review") return false;
  return Boolean(
    detail.list_item.id === candidateId &&
      detail.candidate.id === candidateId &&
      detail.list_item.review_state === expectedReviewState &&
      detail.candidate.review_state === expectedReviewState &&
      detail.list_item.last_client_operation_id == null &&
      detail.candidate.last_client_operation_id == null,
  );
}

/**
 * core state가 먼저 보이고 client operation marker finalizer가 뒤따르는 짧은 창만
 * bounded backoff로 기다린다. needs_review·다른 상태·foreign marker면 즉시 종료한다.
 */
export async function waitForCandidateOperationMarker({
  initial,
  candidateId,
  expectedReviewState,
  fetchCandidateDetail,
  delays = CANDIDATE_OPERATION_MARKER_DELAYS_MS,
  wait = (milliseconds: number) =>
    new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds)),
}: {
  initial: CandidateDetailRevalidation | undefined;
  candidateId: number;
  expectedReviewState: CandidateReviewState;
  fetchCandidateDetail: (candidateId: number) => Promise<CandidateDetail>;
  delays?: readonly number[];
  wait?: (milliseconds: number) => Promise<void>;
}): Promise<CandidateDetailRevalidation | undefined> {
  let current = initial;
  for (const delay of delays) {
    if (
      current?.status !== "success" ||
      !operationMarkerPending(
        current.detail,
        candidateId,
        expectedReviewState,
      )
    ) {
      return current;
    }
    await wait(delay);
    try {
      const detail = await fetchCandidateDetail(candidateId);
      current =
        detail.list_item.id === candidateId && detail.candidate.id === candidateId
          ? { status: "success", detail }
          : {
              status: "error",
              error: new Error("후보 상세 응답의 ID가 요청과 일치하지 않습니다."),
            };
    } catch (error) {
      current = { status: "error", error };
    }
  }
  return current;
}

/**
 * 마지막 단건 처리 하나만 보존한다. 서버 descriptor가 없거나 다중 처리라면 과거
 * descriptor도 지워 "마지막 처리"가 아닌 action을 되돌리는 일을 막는다.
 */
export function applyReviewActionSuccess(
  state: ReviewUndoState,
  success: ReviewActionSuccess,
): ReviewUndoState {
  const generation = state.generation + 1;
  const processedCount = success.processedCount ?? 1;
  const descriptor = success.undo;
  if (
    processedCount !== 1 ||
    !descriptor ||
    descriptor.candidate_id !== success.candidateId ||
    !descriptor.token
  ) {
    return { generation, current: null };
  }
  return {
    generation,
    current: {
      generation,
      descriptor,
      candidateName: success.candidateName,
      action: success.action,
      expectedReviewState: success.reviewState,
    },
  };
}

/** 명시 닫기와 새 bulk 처리 모두 진행 중 undo completion을 무효화한다. */
export function dismissReviewUndo(state: ReviewUndoState): ReviewUndoState {
  return { generation: state.generation + 1, current: null };
}

/**
 * forward mutation 응답이 유실됐을 때 exact detail로 마지막 성공 slot을 복구한다.
 * 기대 상태·undo descriptor뿐 아니라 브라우저가 보낸 client operation ID까지 같아야
 * 같은 상태로 끝난 다른 검수자의 작업을 우리 성공으로 오인하지 않는다.
 * 여전히 needs_review라면 이번 요청은 처리되지 않은 것이므로 이전 성공을 유지한다.
 * 그 밖의 불명·다른 상태는 이전 slot이 더 이상 "마지막"이라고 단정할 수 없어 지운다.
 */
export type ReviewForwardFailureOutcome =
  | "not_committed"
  | "confirmed_committed"
  | "foreign_or_stale"
  | "unknown";

export function reconcileReviewUndoAfterActionFailure(
  state: ReviewUndoState,
  {
    authoritative,
    requestAttempted,
    requestStatus,
    clientOperationId,
    candidateId,
    candidateName,
    action,
    expectedReviewState,
    processedCount = 1,
  }: {
    authoritative: CandidateDetailRevalidation | undefined;
    requestAttempted: boolean;
    requestStatus: number | null;
    clientOperationId: string | null;
    candidateId: number;
    candidateName: string;
    action: ReviewUndoAction;
    expectedReviewState: CandidateReviewState;
    processedCount?: number;
  },
): { state: ReviewUndoState; outcome: ReviewForwardFailureOutcome } {
  if (processedCount !== 1) {
    return { state: dismissReviewUndo(state), outcome: "foreign_or_stale" };
  }
  if (authoritative?.status !== "success") {
    return { state: dismissReviewUndo(state), outcome: "unknown" };
  }
  const candidate = authoritative.detail.list_item;
  if (candidate.id !== candidateId) {
    return { state: dismissReviewUndo(state), outcome: "unknown" };
  }
  if (candidate.review_state === "needs_review") {
    return { state, outcome: "not_committed" };
  }
  if (
    candidate.review_state === expectedReviewState &&
    clientOperationId != null &&
    candidate.last_client_operation_id === clientOperationId &&
    candidate.undo?.candidate_id === candidateId &&
    candidate.undo.token
  ) {
    // 409/4xx는 다른 검수자의 확정 결과일 수 있다. 네트워크 단절 또는 5xx처럼
    // 우리 요청의 commit 이후 응답만 유실됐을 수 있는 경우에만 slot을 승격한다.
    if (requestAttempted && (requestStatus == null || requestStatus >= 500)) {
      return {
        state: applyReviewActionSuccess(state, {
          candidateId,
          candidateName,
          action,
          reviewState: expectedReviewState,
          undo: candidate.undo,
        }),
        outcome: "confirmed_committed",
      };
    }
    return { state: dismissReviewUndo(state), outcome: "foreign_or_stale" };
  }
  return { state: dismissReviewUndo(state), outcome: "foreign_or_stale" };
}

export type ReviewUndoAttempt = {
  generation: number;
  descriptor: CandidateUndoDescriptor;
  expectedReviewState: CandidateReviewState;
  queueScope: string;
  workflowEpoch: number;
};

export function captureReviewUndoAttempt(
  state: ReviewUndoState,
  queueScope: string,
  workflowEpoch: number,
): ReviewUndoAttempt | null {
  const entry = state.current;
  if (!entry) return null;
  return {
    generation: entry.generation,
    descriptor: entry.descriptor,
    expectedReviewState: entry.expectedReviewState,
    queueScope,
    workflowEpoch,
  };
}

/** A→B→A에서도 과거 A 요청은 generation·token·workflow가 모두 같을 때만 UI를 바꾼다. */
export function isCurrentReviewUndoAttempt(
  state: ReviewUndoState,
  attempt: ReviewUndoAttempt,
  currentQueueScope: string,
  currentWorkflowEpoch: number,
): boolean {
  const entry = state.current;
  return Boolean(
    entry &&
      state.generation === attempt.generation &&
      entry.generation === attempt.generation &&
      entry.descriptor.candidate_id === attempt.descriptor.candidate_id &&
      entry.descriptor.token === attempt.descriptor.token &&
      attempt.queueScope === currentQueueScope &&
      attempt.workflowEpoch === currentWorkflowEpoch,
  );
}

export type ReviewUndoRequestOutcome =
  | { kind: "success" }
  | { kind: "error"; status: number | null };

export type ReviewUndoOutcomeClassification =
  | "restored"
  | "retryable"
  | "stale"
  | "unknown";

/**
 * POST 결과보다 직후 exact detail을 우선한다. 409/5xx여도 최신 상태가 needs_review면
 * 복구 완료이고, 5xx 뒤 원 상태가 그대로면 같은 descriptor를 재시도할 수 있다.
 */
export function classifyReviewUndoOutcome({
  request,
  authoritative,
  expectedReviewState,
}: {
  request: ReviewUndoRequestOutcome;
  authoritative: CandidateDetailRevalidation;
  expectedReviewState: CandidateReviewState;
}): ReviewUndoOutcomeClassification {
  if (authoritative.status === "error") return "unknown";
  if (authoritative.status === "not_found") return "stale";

  const currentState = authoritative.detail.list_item.review_state;
  if (currentState === "needs_review") return "restored";
  if (currentState !== expectedReviewState) return "stale";
  if (request.kind === "success") return "unknown";
  if (request.status === 409) return "stale";
  if (request.status == null || request.status >= 500) return "retryable";
  return "stale";
}

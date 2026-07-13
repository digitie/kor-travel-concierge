import { describe, expect, it } from "vitest";

import {
  REVIEW_BULK_CHUNK_SIZE,
  REVIEW_BULK_FILTER_MAX,
  type ReviewBulkExecuteResult,
  type ReviewBulkPreview,
} from "./api";
import {
  beginNextReviewBulkChunk,
  beginReviewBulkPreview,
  cancelReviewBulk,
  confirmReviewBulk,
  createReviewBulkDraft,
  expireReviewBulkConfirmation,
  failReviewBulkExecution,
  failReviewBulkPreview,
  fenceReviewBulkScope,
  INITIAL_REVIEW_BULK_STATE,
  receiveReviewBulkExecution,
  receiveReviewBulkPreview,
  resetReviewBulk,
  retryReviewBulk,
  reviewBulkConfirmationDelayMs,
  reviewBulkConfirmationRef,
  reviewBulkExecuteRef,
  reviewBulkExecuteRequest,
  reviewBulkPreviewRef,
  reviewBulkPreviewRequest,
  reviewBulkScopeKey,
  type ReviewBulkConfirmState,
  type ReviewBulkExecutingState,
  type ReviewBulkPreviewingState,
} from "./review-bulk";

const NOW_MS = Date.parse("2026-07-14T12:00:00Z");
const LATER_MS = NOW_MS + 5 * 60 * 1000;
const REQUEST_1 = "11111111-1111-4111-8111-111111111111";
const REQUEST_2 = "22222222-2222-4222-8222-222222222222";
const OPERATION_1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const OPERATION_2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const TOKEN_1 = `rbulk1.${OPERATION_1}.opaque_confirmation_token`;
const TOKEN_2 = `rbulk1.${OPERATION_2}.other_confirmation_token`;

const DRAFT_A = createReviewBulkDraft("ignore", {
  kind: "filter",
  filter: {
    q: "제주",
    is_domestic: null,
    status: "needs_review",
  },
});
const DRAFT_B = createReviewBulkDraft("ignore", {
  kind: "filter",
  filter: {
    q: "부산",
    is_domestic: null,
    status: "needs_review",
  },
});

function preview(
  overrides: Partial<ReviewBulkPreview> = {},
): ReviewBulkPreview {
  return {
    operation_id: OPERATION_1,
    confirmation_token: TOKEN_1,
    expires_at: new Date(NOW_MS + 60_000).toISOString(),
    total: 3,
    chunk_size: REVIEW_BULK_CHUNK_SIZE,
    ...overrides,
  };
}

function previewing(): ReviewBulkPreviewingState {
  const state = beginReviewBulkPreview(INITIAL_REVIEW_BULK_STATE, DRAFT_A);
  if (state.status !== "previewing") throw new Error("previewing 전이 실패");
  return state;
}

function confirming(
  value: ReviewBulkPreview = preview(),
): ReviewBulkConfirmState {
  const state = previewing();
  const ref = reviewBulkPreviewRef(state);
  if (ref == null) throw new Error("preview ref 생성 실패");
  const received = receiveReviewBulkPreview(state, ref, value, NOW_MS);
  if (received.status !== "confirm") throw new Error("confirm 전이 실패");
  return received;
}

function executing(
  value: ReviewBulkPreview = preview(),
): ReviewBulkExecutingState {
  const state = confirmReviewBulk(confirming(value), REQUEST_1, NOW_MS);
  if (state.status !== "executing") throw new Error("executing 전이 실패");
  return state;
}

function receipt(
  overrides: Partial<ReviewBulkExecuteResult> = {},
): ReviewBulkExecuteResult {
  return {
    operation_id: OPERATION_1,
    request_id: REQUEST_1,
    processed: 3,
    succeeded: 3,
    conflicts: [],
    failed: [],
    remaining: 0,
    next_cursor: null,
    complete: true,
    ...overrides,
  };
}

function expectTokenFree(state: unknown) {
  expect(JSON.stringify(state)).not.toContain(TOKEN_1);
}

describe("검수 bulk scope와 세대 fencing", () => {
  it("선택 순서·중복·object identity와 무관하게 같은 scope key를 만든다", () => {
    expect(
      reviewBulkScopeKey({
        kind: "selection",
        candidateIds: [42, 7, 42],
      }),
    ).toBe(
      reviewBulkScopeKey({ kind: "selection", candidateIds: [7, 42] }),
    );
    expect(
      reviewBulkScopeKey({
        kind: "filter",
        filter: {
          q: " 제주 ",
          is_domestic: false,
          status: "needs_review",
        },
      }),
    ).toBe(
      reviewBulkScopeKey({
        kind: "filter",
        filter: {
          q: "제주",
          is_domestic: false,
          status: "needs_review",
        },
      }),
    );
  });

  it("is_domestic false와 null은 서로 다른 filter membership이다", () => {
    const foreign = reviewBulkScopeKey({
      kind: "filter",
      filter: { is_domestic: false, status: "needs_review" },
    });
    const all = reviewBulkScopeKey({
      kind: "filter",
      filter: { is_domestic: null, status: "needs_review" },
    });

    expect(foreign).not.toBe(all);
  });

  it("A→B→A로 돌아와도 sequence가 달라 첫 A 응답을 거부한다", () => {
    const firstA = previewing();
    const firstRef = reviewBulkPreviewRef(firstA);
    if (firstRef == null) throw new Error("preview ref 생성 실패");

    const middleB = fenceReviewBulkScope(firstA, DRAFT_B);
    const latestA = beginReviewBulkPreview(middleB, DRAFT_A);

    expect(middleB.status).toBe("idle");
    expect(middleB.sequence).toBe(firstA.sequence + 1);
    expect(latestA.status).toBe("previewing");
    expect(latestA.sequence).toBe(middleB.sequence + 1);
    expect(
      receiveReviewBulkPreview(latestA, firstRef, preview(), NOW_MS),
    ).toBe(latestA);
  });

  it("같은 scope라도 action이 바뀌면 기존 preview를 폐기한다", () => {
    const first = previewing();
    const deleteDraft = createReviewBulkDraft("delete", DRAFT_A.scope);
    const fenced = fenceReviewBulkScope(first, deleteDraft);

    expect(deleteDraft.fenceKey).not.toBe(DRAFT_A.fenceKey);
    expect(fenced).toEqual({
      status: "idle",
      sequence: first.sequence + 1,
      fenceKey: deleteDraft.fenceKey,
    });
  });

  it("동일 preview 버튼 연타는 새 세대나 중복 요청을 만들지 않는다", () => {
    const first = previewing();

    expect(beginReviewBulkPreview(first, DRAFT_A)).toBe(first);
    expect(reviewBulkPreviewRequest(first)).toEqual({
      action: "ignore",
      scope: DRAFT_A.scope,
    });
  });
});

describe("검수 bulk preview와 확인", () => {
  it("유효 preview의 count/token/operation/expiry를 confirm 메모리 상태에 보존한다", () => {
    const state = confirming();

    expect(state.preview).toEqual(preview());
    expect(state.preview.total).toBe(3);
    expect(state.preview.confirmation_token).toBe(TOKEN_1);
  });

  it("이미 만료됐거나 응답 계약이 손상된 preview를 실행하지 않는다", () => {
    const expiredSource = previewing();
    const expiredRef = reviewBulkPreviewRef(expiredSource);
    if (expiredRef == null) throw new Error("preview ref 생성 실패");
    const expired = receiveReviewBulkPreview(
      expiredSource,
      expiredRef,
      preview({ expires_at: new Date(NOW_MS).toISOString() }),
      NOW_MS,
    );

    const invalidSource = previewing();
    const invalidRef = reviewBulkPreviewRef(invalidSource);
    if (invalidRef == null) throw new Error("preview ref 생성 실패");
    const invalid = receiveReviewBulkPreview(
      invalidSource,
      invalidRef,
      preview({ operation_id: "" }),
      NOW_MS,
    );

    expect(expired.status).toBe("expired");
    expect(expired).not.toHaveProperty("preview.confirmation_token");
    expectTokenFree(expired);
    expect(invalid).toMatchObject({
      status: "error",
      phase: "preview",
      retryable: false,
    });
  });

  it("selection preview의 고지 건수가 canonical 선택 개수와 다르면 거부한다", () => {
    const draft = createReviewBulkDraft("delete", {
      kind: "selection",
      candidateIds: [42, 7, 42],
    });
    const source = beginReviewBulkPreview(INITIAL_REVIEW_BULK_STATE, draft);
    const ref = reviewBulkPreviewRef(source);
    if (ref == null) throw new Error("selection preview ref 생성 실패");

    expect(
      receiveReviewBulkPreview(source, ref, preview({ total: 1 }), NOW_MS),
    ).toMatchObject({
      status: "error",
      phase: "preview",
      retryable: false,
    });
  });

  it("서버 고정 chunk 크기와 다른 preview 응답을 거부한다", () => {
    const source = previewing();
    const ref = reviewBulkPreviewRef(source);
    if (ref == null) throw new Error("preview ref 생성 실패");

    expect(
      receiveReviewBulkPreview(
        source,
        ref,
        preview({ chunk_size: REVIEW_BULK_CHUNK_SIZE - 1 }),
        NOW_MS,
      ),
    ).toMatchObject({
      status: "error",
      phase: "preview",
      retryable: false,
    });
  });

  it("filter 안전 상한을 넘는 preview 응답을 거부한다", () => {
    const source = previewing();
    const ref = reviewBulkPreviewRef(source);
    if (ref == null) throw new Error("preview ref 생성 실패");

    expect(
      receiveReviewBulkPreview(
        source,
        ref,
        preview({ total: REVIEW_BULK_FILTER_MAX + 1 }),
        NOW_MS,
      ),
    ).toMatchObject({
      status: "error",
      phase: "preview",
      retryable: false,
    });
  });

  it("operation UUID와 결합되지 않은 confirmation token을 거부한다", () => {
    const source = previewing();
    const ref = reviewBulkPreviewRef(source);
    if (ref == null) throw new Error("preview ref 생성 실패");

    expect(
      receiveReviewBulkPreview(
        source,
        ref,
        preview({ confirmation_token: TOKEN_2 }),
        NOW_MS,
      ),
    ).toMatchObject({
      status: "error",
      phase: "preview",
      retryable: false,
    });
  });

  it("preview 네트워크 재시도는 sequence를 올리고 이전 응답을 거부한다", () => {
    const source = previewing();
    const oldRef = reviewBulkPreviewRef(source);
    if (oldRef == null) throw new Error("preview ref 생성 실패");
    const failed = failReviewBulkPreview(source, oldRef, {
      kind: "retryable",
      message: "network lost",
    });
    const retried = retryReviewBulk(failed, LATER_MS);

    expect(retried.status).toBe("previewing");
    expect(retried.sequence).toBe(source.sequence + 1);
    expect(
      receiveReviewBulkPreview(retried, oldRef, preview(), NOW_MS),
    ).toBe(retried);
  });

  it("confirm 직전 만료를 막고 confirm 버튼 연타는 첫 execute만 유지한다", () => {
    const nearExpiry = confirming(
      preview({ expires_at: new Date(NOW_MS + 1_000).toISOString() }),
    );
    const expired = confirmReviewBulk(nearExpiry, REQUEST_1, NOW_MS + 1_001);

    const valid = confirmReviewBulk(confirming(), REQUEST_1, NOW_MS);
    const duplicate = confirmReviewBulk(valid, REQUEST_2, NOW_MS);

    expect(expired.status).toBe("expired");
    expect(expired).not.toHaveProperty("preview.confirmation_token");
    expectTokenFree(expired);
    expect(valid.status).toBe("executing");
    expect(duplicate).toBe(valid);
    expect(reviewBulkExecuteRequest(valid)).toEqual({
      operationId: OPERATION_1,
      confirmationToken: TOKEN_1,
      cursor: null,
      requestId: REQUEST_1,
    });
  });

  it("confirm timer 만료는 0건 preview도 token-free expired로 전이한다", () => {
    const state = confirming(
      preview({
        total: 0,
        expires_at: new Date(NOW_MS + 1_000).toISOString(),
      }),
    );
    const ref = reviewBulkConfirmationRef(state);
    if (ref == null) throw new Error("confirm expiry ref 생성 실패");

    expect(expireReviewBulkConfirmation(state, ref, NOW_MS + 999)).toBe(
      state,
    );
    const expired = expireReviewBulkConfirmation(state, ref, NOW_MS + 1_000);

    expect(expired).toMatchObject({
      status: "expired",
      preview: { total: 0 },
    });
    expect(expired).not.toHaveProperty("preview.confirmation_token");
    expectTokenFree(expired);
  });

  it("confirm timer는 이전 sequence를 만료시키지 않고 긴 delay를 32-bit 상한으로 제한한다", () => {
    const oldState = confirming(
      preview({ expires_at: new Date(NOW_MS + 1_000).toISOString() }),
    );
    const oldRef = reviewBulkConfirmationRef(oldState);
    if (oldRef == null) throw new Error("old confirm expiry ref 생성 실패");
    const nextPreviewing = beginReviewBulkPreview(oldState, DRAFT_A);
    const nextRef = reviewBulkPreviewRef(nextPreviewing);
    if (nextRef == null) throw new Error("next preview ref 생성 실패");
    const nextState = receiveReviewBulkPreview(
      nextPreviewing,
      nextRef,
      preview({
        operation_id: OPERATION_2,
        confirmation_token: TOKEN_2,
        expires_at: new Date(NOW_MS + 120_000).toISOString(),
      }),
      NOW_MS,
    );

    expect(nextState.status).toBe("confirm");
    expect(
      expireReviewBulkConfirmation(nextState, oldRef, NOW_MS + 1_000),
    ).toBe(nextState);
    expect(
      reviewBulkConfirmationDelayMs("2099-01-01T00:00:00Z", NOW_MS),
    ).toBe(2_147_483_647);
    expect(
      reviewBulkConfirmationDelayMs(
        new Date(NOW_MS - 1).toISOString(),
        NOW_MS,
      ),
    ).toBe(0);
  });
});

describe("검수 bulk chunk 실행과 멱등 재시도", () => {
  it("chunk 증분을 누적하고 5분 경과 후에도 같은 cursor/request_id 재시도를 계속한다", () => {
    const first = executing();
    const firstRef = reviewBulkExecuteRef(first);
    if (firstRef == null) throw new Error("execute ref 생성 실패");
    const firstResult = receipt({
      processed: 2,
      succeeded: 1,
      conflicts: [
        { candidate_id: 42, code: "state_conflict", message: "상태 변경" },
      ],
      remaining: 1,
      next_cursor: "cursor-2",
      complete: false,
    });
    const afterFirst = receiveReviewBulkExecution(
      first,
      firstRef,
      firstResult,
    );
    if (afterFirst.status !== "executing") {
      throw new Error("첫 chunk 누적 실패");
    }

    expect(afterFirst.progress).toMatchObject({
      total: 3,
      processed: 2,
      succeeded: 1,
      remaining: 1,
      cursor: "cursor-2",
    });
    expect(afterFirst.request).toBeNull();
    expect(
      receiveReviewBulkExecution(afterFirst, firstRef, firstResult),
    ).toBe(afterFirst);

    const second = beginNextReviewBulkChunk(
      afterFirst,
      REQUEST_2,
      LATER_MS,
    );
    if (second.status !== "executing" || second.request == null) {
      throw new Error("두 번째 chunk 시작 실패");
    }
    const secondRef = reviewBulkExecuteRef(second);
    const beforeRetry = reviewBulkExecuteRequest(second);
    if (secondRef == null || beforeRetry == null) {
      throw new Error("두 번째 execute command 생성 실패");
    }
    const responseLost = failReviewBulkExecution(second, secondRef, {
      kind: "retryable",
      message: "response lost",
    });
    expect(responseLost).toMatchObject({
      status: "error",
      phase: "execute",
      retryable: true,
      preview: { confirmation_token: TOKEN_1 },
      progress: {
        total: 3,
        processed: 2,
        succeeded: 1,
        remaining: 1,
      },
      request: { cursor: "cursor-2", requestId: REQUEST_2 },
    });
    expect(JSON.stringify(responseLost)).toContain(TOKEN_1);
    const retried = retryReviewBulk(responseLost, LATER_MS + 60_000);

    expect(retried.status).toBe("executing");
    expect(reviewBulkExecuteRequest(retried)).toEqual(beforeRetry);
    expect(beforeRetry).toMatchObject({
      cursor: "cursor-2",
      requestId: REQUEST_2,
    });

    const completed = receiveReviewBulkExecution(
      retried,
      secondRef,
      receipt({
        request_id: REQUEST_2,
        processed: 1,
        succeeded: 1,
      }),
    );
    expect(completed.status).toBe("partial");
    if (completed.status !== "partial") throw new Error("partial 전이 실패");
    expect(completed.progress).toMatchObject({
      total: 3,
      processed: 3,
      succeeded: 2,
      remaining: 0,
    });
    expect(completed.progress.conflicts).toHaveLength(1);
    expect(completed).not.toHaveProperty("preview.confirmation_token");
    expectTokenFree(completed);
    expect(
      receiveReviewBulkExecution(completed, secondRef, receipt()),
    ).toBe(completed);
  });

  it("모든 chunk가 성공하면 completed로 끝내고 terminal state에서 token을 폐기한다", () => {
    const state = executing(preview({ total: 2, chunk_size: 100 }));
    const ref = reviewBulkExecuteRef(state);
    if (ref == null) throw new Error("execute ref 생성 실패");

    const completed = receiveReviewBulkExecution(
      state,
      ref,
      receipt({ processed: 2, succeeded: 2 }),
    );

    expect(completed.status).toBe("completed");
    expect(completed).not.toHaveProperty("preview.confirmation_token");
    expectTokenFree(completed);
  });

  it("서버가 명시적으로 만료를 응답할 때만 시작된 operation을 expired로 끝낸다", () => {
    const first = executing();
    const firstRef = reviewBulkExecuteRef(first);
    if (firstRef == null) throw new Error("첫 execute ref 생성 실패");
    const afterFirst = receiveReviewBulkExecution(
      first,
      firstRef,
      receipt({
        processed: 2,
        succeeded: 1,
        conflicts: [
          { candidate_id: 42, code: "state_conflict", message: "상태 변경" },
        ],
        remaining: 1,
        next_cursor: "cursor-2",
        complete: false,
      }),
    );
    if (afterFirst.status !== "executing") {
      throw new Error("첫 chunk 누적 실패");
    }
    const state = beginNextReviewBulkChunk(afterFirst, REQUEST_2);
    const ref = reviewBulkExecuteRef(state);
    if (ref == null) throw new Error("두 번째 execute ref 생성 실패");

    const expired = failReviewBulkExecution(state, ref, {
      kind: "expired",
      message: "server returned 410",
    });

    expect(expired).toMatchObject({
      status: "expired",
      message: "server returned 410",
      progress: {
        total: 3,
        processed: 2,
        succeeded: 1,
        conflicts: 1,
        failed: 0,
        remaining: 1,
      },
    });
    expect(expired).not.toHaveProperty("preview.confirmation_token");
    expect(expired).not.toHaveProperty("progress.cursor");
    expectTokenFree(expired);
  });

  it("fatal execute 오류는 token/request를 폐기하되 확인된 누적 progress summary를 보존한다", () => {
    const first = executing();
    const firstRef = reviewBulkExecuteRef(first);
    if (firstRef == null) throw new Error("첫 execute ref 생성 실패");
    const afterFirst = receiveReviewBulkExecution(
      first,
      firstRef,
      receipt({
        processed: 2,
        succeeded: 1,
        conflicts: [
          { candidate_id: 42, code: "state_conflict", message: "상태 변경" },
        ],
        remaining: 1,
        next_cursor: "cursor-2",
        complete: false,
      }),
    );
    const state = beginNextReviewBulkChunk(afterFirst, REQUEST_2);
    const ref = reviewBulkExecuteRef(state);
    if (ref == null) throw new Error("두 번째 execute ref 생성 실패");

    const terminal = failReviewBulkExecution(state, ref, {
      kind: "fatal",
      message: "forbidden",
    });

    expect(terminal).toMatchObject({
      status: "error",
      phase: "terminal",
      retryable: false,
      message: "forbidden",
      terminalKind: "fatal",
      progress: {
        total: 3,
        processed: 2,
        succeeded: 1,
        conflicts: 1,
        failed: 0,
        remaining: 1,
      },
    });
    expect(terminal).not.toHaveProperty("preview");
    expect(terminal).not.toHaveProperty("request");
    expectTokenFree(terminal);
    expect(retryReviewBulk(terminal, LATER_MS)).toBe(terminal);
  });

  it("409 실행 충돌은 token-free stale terminal과 목록 재확인용 summary로 끝낸다", () => {
    const state = executing();
    const ref = reviewBulkExecuteRef(state);
    if (ref == null) throw new Error("execute ref 생성 실패");

    const terminal = failReviewBulkExecution(state, ref, {
      kind: "stale_conflict",
      message: "stale cursor",
    });

    expect(terminal).toMatchObject({
      status: "error",
      phase: "terminal",
      terminalKind: "stale_conflict",
      progress: {
        total: 3,
        processed: 0,
        succeeded: 0,
        conflicts: 0,
        failed: 0,
        remaining: 3,
      },
    });
    expect(terminal).not.toHaveProperty("preview");
    expect(terminal).not.toHaveProperty("request");
    expectTokenFree(terminal);
  });

  it("다른 request/세대 응답은 현재 progress를 오염시키지 않는다", () => {
    const state = executing();
    const ref = reviewBulkExecuteRef(state);
    if (ref == null) throw new Error("execute ref 생성 실패");

    expect(
      receiveReviewBulkExecution(
        state,
        { ...ref, requestId: REQUEST_2 },
        receipt({ request_id: REQUEST_2 }),
      ),
    ).toBe(state);
    expect(
      receiveReviewBulkExecution(
        state,
        { ...ref, sequence: ref.sequence + 1 },
        receipt(),
      ),
    ).toBe(state);
  });
});

describe("검수 bulk receipt 계약 검증", () => {
  function expectContractError(
    result: ReviewBulkExecuteResult,
    previewValue: ReviewBulkPreview = preview(),
  ) {
    const state = executing(previewValue);
    const ref = reviewBulkExecuteRef(state);
    if (ref == null) throw new Error("execute ref 생성 실패");

    const terminal = receiveReviewBulkExecution(state, ref, result);
    expect(terminal).toMatchObject({
      status: "error",
      phase: "terminal",
      retryable: false,
      terminalKind: "contract",
      draft: state.draft,
      progress: {
        total: previewValue.total,
        processed: 0,
        succeeded: 0,
        conflicts: 0,
        failed: 0,
        remaining: previewValue.total,
      },
    });
    expect(terminal).not.toHaveProperty("preview");
    expect(terminal).not.toHaveProperty("request");
    expectTokenFree(terminal);
    expect(retryReviewBulk(terminal, LATER_MS)).toBe(terminal);
  }

  it("processed와 succeeded/conflicts/failed chunk 합계 불일치를 거부한다", () => {
    expectContractError(
      receipt({
        processed: 2,
        succeeded: 2,
        conflicts: [
          { candidate_id: 42, code: "conflict", message: "충돌" },
        ],
      }),
    );
  });

  it("candidate_id/code/message가 손상된 issue를 거부한다", () => {
    expectContractError(
      receipt({
        processed: 2,
        succeeded: 1,
        failed: [{ candidate_id: 0, code: "", message: "" }],
      }),
    );
  });

  it("서버 고정 chunk_size보다 큰 receipt를 거부한다", () => {
    expectContractError(
      receipt({
        processed: REVIEW_BULK_CHUNK_SIZE + 1,
        succeeded: REVIEW_BULK_CHUNK_SIZE + 1,
      }),
      preview({ total: REVIEW_BULK_CHUNK_SIZE + 1 }),
    );
  });

  it("누적 processed + remaining이 preview total과 다르면 거부한다", () => {
    expectContractError(
      receipt({
        processed: 1,
        succeeded: 1,
        remaining: 1,
        next_cursor: "cursor-2",
        complete: false,
      }),
    );
  });

  it("미완료 chunk가 non-advancing cursor를 주면 무한 반복 대신 오류로 끝낸다", () => {
    expectContractError(
      receipt({
        processed: 2,
        succeeded: 2,
        remaining: 1,
        next_cursor: null,
        complete: false,
      }),
    );
  });
});

describe("검수 bulk 취소와 token 수명", () => {
  it("previewing reset 뒤 도착한 응답은 무시한다", () => {
    const state = previewing();
    const ref = reviewBulkPreviewRef(state);
    if (ref == null) throw new Error("preview ref 생성 실패");
    const reset = resetReviewBulk(state);

    expect(reset).toEqual({
      status: "idle",
      sequence: state.sequence + 1,
      fenceKey: state.fenceKey,
    });
    expect(reset).not.toHaveProperty("preview");
    expect(reset).not.toHaveProperty("confirmation_token");
    expectTokenFree(reset);
    expect(receiveReviewBulkPreview(reset, ref, preview(), NOW_MS)).toBe(reset);
  });

  it("실행 취소는 메모리 token을 폐기하고 늦은 receipt를 무시한다", () => {
    const state = executing();
    const ref = reviewBulkExecuteRef(state);
    if (ref == null) throw new Error("execute ref 생성 실패");
    const cancelled = cancelReviewBulk(state);

    expect(cancelled.status).toBe("idle");
    expect(cancelled).not.toHaveProperty("preview");
    expect(cancelled).not.toHaveProperty("confirmation_token");
    expectTokenFree(cancelled);
    expect(receiveReviewBulkExecution(cancelled, ref, receipt())).toBe(
      cancelled,
    );
  });
});

import { describe, expect, it } from "vitest";

import type {
  CandidateDetail,
  CandidateReviewState,
  UnmatchedCandidate,
} from "./api";
import type { CandidateDetailRevalidation } from "./review-candidate-cache";
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
  REVIEW_UNDO_HANDOFF_TTL_MS,
  serializeReviewUndoHandoff,
  waitForCandidateOperationMarker,
} from "./review-undo";

function listItem(reviewState: CandidateReviewState): UnmatchedCandidate {
  return {
    id: 1,
    video_id: "video-1",
    video_title: "영상 1",
    channel_title: null,
    ai_place_name: "후보 1",
    location_hint: null,
    candidate_category: null,
    candidate_category_code: null,
    match_status:
      reviewState === "deleted" ? "needs_review" : reviewState,
    review_state: reviewState,
    state_revision: 8,
    last_client_operation_id: null,
    video_is_excluded: false,
    undo: null,
    confidence_score: null,
    source_kind: "transcript",
    grounding_status: "verified_raw",
    created_at: "2026-07-13T00:00:00Z",
    queue_reason: "extraction_only",
    timestamp_start: null,
    is_domestic: true,
  };
}

function authoritative(
  reviewState: CandidateReviewState,
): CandidateDetailRevalidation {
  const item = listItem(reviewState);
  const detail: CandidateDetail = {
    list_item: item,
    candidate: {
      id: item.id,
      video_id: item.video_id,
      source_channel_id: null,
      source_playlist_id: null,
      ai_place_name: item.ai_place_name,
      location_hint: null,
      candidate_category: null,
      candidate_category_code: null,
      match_status: item.match_status,
      review_state: item.review_state,
      state_revision: item.state_revision,
      last_client_operation_id: item.last_client_operation_id,
      video_is_excluded: item.video_is_excluded,
      undo: null,
      confidence_score: null,
      grounding_status: item.grounding_status,
      is_domestic: true,
      speaker_note: null,
      source_kind: "transcript",
      feature_export_status: "pending",
      timestamp_start: null,
      timestamp_end: null,
      source_text: null,
    },
    video: null,
    source_run: null,
    provider_evidence: null,
    sibling_candidates: [],
  };
  return { status: "success", detail };
}

describe("마지막 단건 undo slot", () => {
  it("새 단건 성공이 이전 descriptor를 교체하고 stack을 만들지 않는다", () => {
    const first = applyReviewActionSuccess(INITIAL_REVIEW_UNDO_STATE, {
      candidateId: 1,
      candidateName: "후보 1",
      action: "ignore",
      reviewState: "ignored",
      undo: { candidate_id: 1, token: "token-a" },
    });
    const second = applyReviewActionSuccess(first, {
      candidateId: 2,
      candidateName: "후보 2",
      action: "delete",
      reviewState: "deleted",
      undo: { candidate_id: 2, token: "token-b" },
    });

    expect(first.current?.descriptor.token).toBe("token-a");
    expect(second.generation).toBe(2);
    expect(second.current).toMatchObject({
      candidateName: "후보 2",
      descriptor: { candidate_id: 2, token: "token-b" },
    });
    expect(Array.isArray(second.current)).toBe(false);
  });

  it("bulk·descriptor 누락·candidate 불일치 성공은 과거 undo도 지운다", () => {
    const active = applyReviewActionSuccess(INITIAL_REVIEW_UNDO_STATE, {
      candidateId: 1,
      candidateName: "후보 1",
      action: "ignore",
      reviewState: "ignored",
      undo: { candidate_id: 1, token: "token-a" },
    });
    const bulk = applyReviewActionSuccess(active, {
      candidateId: 2,
      candidateName: "후보 2 외",
      action: "delete",
      reviewState: "deleted",
      undo: { candidate_id: 2, token: "bulk-token" },
      processedCount: 2,
    });
    const missing = applyReviewActionSuccess(active, {
      candidateId: 2,
      candidateName: "후보 2",
      action: "ignore",
      reviewState: "ignored",
    });
    const mismatch = applyReviewActionSuccess(active, {
      candidateId: 2,
      candidateName: "후보 2",
      action: "ignore",
      reviewState: "ignored",
      undo: { candidate_id: 3, token: "wrong-candidate" },
    });

    expect(bulk.current).toBeNull();
    expect(missing.current).toBeNull();
    expect(mismatch.current).toBeNull();
    expect(bulk.generation).toBe(active.generation + 1);
  });

  it("명시 닫기는 slot과 진행 중 completion generation을 함께 무효화한다", () => {
    const active = applyReviewActionSuccess(INITIAL_REVIEW_UNDO_STATE, {
      candidateId: 1,
      candidateName: "후보 1",
      action: "ignore",
      reviewState: "ignored",
      undo: { candidate_id: 1, token: "token-a" },
    });
    const attempt = captureReviewUndoAttempt(active, "scope-a", 3);
    if (!attempt) throw new Error("undo attempt 누락");

    const dismissed = dismissReviewUndo(active);

    expect(dismissed.current).toBeNull();
    expect(
      isCurrentReviewUndoAttempt(dismissed, attempt, "scope-a", 3),
    ).toBe(false);
  });

  it("늦은 A 응답과 scope A→B→A의 과거 workflow를 current로 되살리지 않는다", () => {
    const stateA = applyReviewActionSuccess(INITIAL_REVIEW_UNDO_STATE, {
      candidateId: 1,
      candidateName: "후보 1",
      action: "ignore",
      reviewState: "ignored",
      undo: { candidate_id: 1, token: "token-a" },
    });
    const attemptA = captureReviewUndoAttempt(stateA, "scope-a", 10);
    if (!attemptA) throw new Error("A undo attempt 누락");
    const stateB = applyReviewActionSuccess(stateA, {
      candidateId: 2,
      candidateName: "후보 2",
      action: "delete",
      reviewState: "deleted",
      undo: { candidate_id: 2, token: "token-b" },
    });
    const attemptB = captureReviewUndoAttempt(stateB, "scope-a", 11);
    if (!attemptB) throw new Error("B undo attempt 누락");

    expect(
      isCurrentReviewUndoAttempt(stateB, attemptA, "scope-a", 10),
    ).toBe(false);
    expect(
      isCurrentReviewUndoAttempt(stateB, attemptB, "scope-a", 13),
    ).toBe(false);
    expect(
      isCurrentReviewUndoAttempt(stateB, attemptB, "scope-a", 11),
    ).toBe(true);
  });
});

describe("undo 409/5xx 권위 상태 판정", () => {
  it("409나 5xx여도 exact detail이 needs_review면 복구 완료다", () => {
    expect(
      classifyReviewUndoOutcome({
        request: { kind: "error", status: 409 },
        authoritative: authoritative("needs_review"),
        expectedReviewState: "ignored",
      }),
    ).toBe("restored");
    expect(
      classifyReviewUndoOutcome({
        request: { kind: "error", status: 503 },
        authoritative: authoritative("needs_review"),
        expectedReviewState: "deleted",
      }),
    ).toBe("restored");
  });

  it("5xx 뒤 같은 post-action 상태면 재시도하고 다른 상태면 stale로 닫는다", () => {
    expect(
      classifyReviewUndoOutcome({
        request: { kind: "error", status: 500 },
        authoritative: authoritative("ignored"),
        expectedReviewState: "ignored",
      }),
    ).toBe("retryable");
    expect(
      classifyReviewUndoOutcome({
        request: { kind: "error", status: null },
        authoritative: authoritative("deleted"),
        expectedReviewState: "deleted",
      }),
    ).toBe("retryable");
    expect(
      classifyReviewUndoOutcome({
        request: { kind: "error", status: 500 },
        authoritative: authoritative("user_corrected"),
        expectedReviewState: "ignored",
      }),
    ).toBe("stale");
  });

  it("409에서 원 상태가 그대로여도 descriptor fencing 충돌이므로 stale이다", () => {
    expect(
      classifyReviewUndoOutcome({
        request: { kind: "error", status: 409 },
        authoritative: authoritative("ignored"),
        expectedReviewState: "ignored",
      }),
    ).toBe("stale");
  });

  it("상세 재검증 자체가 실패하면 결과 불명으로 보존한다", () => {
    expect(
      classifyReviewUndoOutcome({
        request: { kind: "error", status: 500 },
        authoritative: { status: "error", error: new Error("detail 500") },
        expectedReviewState: "ignored",
      }),
    ).toBe("unknown");
  });
});

describe("forward 응답 유실 뒤 마지막 성공 복구", () => {
  const attemptedOperationId = "11111111-1111-4111-8111-111111111111";
  const previous = applyReviewActionSuccess(INITIAL_REVIEW_UNDO_STATE, {
    candidateId: 9,
    candidateName: "이전 후보",
    action: "ignore",
    reviewState: "ignored",
    undo: { candidate_id: 9, token: "previous-token" },
  });

  it("exact detail이 기대 post-state와 token이면 새 단건 성공으로 교체한다", () => {
    const deleted = authoritative("deleted");
    if (deleted.status !== "success") throw new Error("상세 fixture 오류");
    deleted.detail.list_item.undo = {
      candidate_id: 1,
      token: "recovered-delete-token",
    };
    deleted.detail.list_item.last_client_operation_id = attemptedOperationId;

    const next = reconcileReviewUndoAfterActionFailure(previous, {
      authoritative: deleted,
      requestAttempted: true,
      requestStatus: 500,
      clientOperationId: attemptedOperationId,
      candidateId: 1,
      candidateName: "후보 1",
      action: "delete",
      expectedReviewState: "deleted",
    });

    expect(next.outcome).toBe("confirmed_committed");
    expect(next.state.current).toMatchObject({
      candidateName: "후보 1",
      action: "delete",
      descriptor: { token: "recovered-delete-token" },
    });
  });

  it("후보가 그대로 needs_review면 이전 성공을 유지한다", () => {
    const next = reconcileReviewUndoAfterActionFailure(previous, {
      authoritative: authoritative("needs_review"),
      requestAttempted: true,
      requestStatus: 500,
      clientOperationId: attemptedOperationId,
      candidateId: 1,
      candidateName: "후보 1",
      action: "ignore",
      expectedReviewState: "ignored",
    });
    expect(next.outcome).toBe("not_committed");
    expect(next.state).toBe(previous);
  });

  it("상태가 다르거나 exact detail이 불명확하면 거짓 이전 slot을 지운다", () => {
    const changedElsewhere = reconcileReviewUndoAfterActionFailure(previous, {
      authoritative: authoritative("matched"),
      requestAttempted: true,
      requestStatus: 500,
      clientOperationId: attemptedOperationId,
      candidateId: 1,
      candidateName: "후보 1",
      action: "ignore",
      expectedReviewState: "ignored",
    });
    const unknown = reconcileReviewUndoAfterActionFailure(previous, {
      authoritative: { status: "error", error: new Error("detail 500") },
      requestAttempted: true,
      requestStatus: null,
      clientOperationId: attemptedOperationId,
      candidateId: 1,
      candidateName: "후보 1",
      action: "delete",
      expectedReviewState: "deleted",
    });

    expect(changedElsewhere.state.current).toBeNull();
    expect(unknown.state.current).toBeNull();
  });

  it("409 exact post-state는 다른 검수자 결과일 수 있어 slot으로 승격하지 않는다", () => {
    const ignored = authoritative("ignored");
    if (ignored.status !== "success") throw new Error("상세 fixture 오류");
    ignored.detail.list_item.undo = {
      candidate_id: 1,
      token: "foreign-ignore-token",
    };
    ignored.detail.list_item.last_client_operation_id = attemptedOperationId;

    const next = reconcileReviewUndoAfterActionFailure(previous, {
      authoritative: ignored,
      requestAttempted: true,
      requestStatus: 409,
      clientOperationId: attemptedOperationId,
      candidateId: 1,
      candidateName: "후보 1",
      action: "ignore",
      expectedReviewState: "ignored",
    });

    expect(next.outcome).toBe("foreign_or_stale");
    expect(next.state.current).toBeNull();
  });

  it("DELETE를 보내기 전 preflight에서 본 post-state는 우리 성공으로 승격하지 않는다", () => {
    const deleted = authoritative("deleted");
    if (deleted.status !== "success") throw new Error("상세 fixture 오류");
    deleted.detail.list_item.undo = {
      candidate_id: 1,
      token: "foreign-preflight-token",
    };
    deleted.detail.list_item.last_client_operation_id = attemptedOperationId;

    const next = reconcileReviewUndoAfterActionFailure(previous, {
      authoritative: deleted,
      requestAttempted: false,
      requestStatus: null,
      clientOperationId: attemptedOperationId,
      candidateId: 1,
      candidateName: "후보 1",
      action: "delete",
      expectedReviewState: "deleted",
    });

    expect(next.outcome).toBe("foreign_or_stale");
    expect(next.state.current).toBeNull();
  });

  it("5xx 뒤 기대 상태와 token이 같아도 operation ID가 다르면 승격하지 않는다", () => {
    const deleted = authoritative("deleted");
    if (deleted.status !== "success") throw new Error("상세 fixture 오류");
    deleted.detail.list_item.undo = {
      candidate_id: 1,
      token: "foreign-delete-token",
    };
    deleted.detail.list_item.last_client_operation_id =
      "99999999-9999-4999-8999-999999999999";

    const next = reconcileReviewUndoAfterActionFailure(previous, {
      authoritative: deleted,
      requestAttempted: true,
      requestStatus: 500,
      clientOperationId: attemptedOperationId,
      candidateId: 1,
      candidateName: "후보 1",
      action: "delete",
      expectedReviewState: "deleted",
    });

    expect(next.outcome).toBe("foreign_or_stale");
    expect(next.state.current).toBeNull();
  });
});

describe("모바일 상세 undo handoff", () => {
  it("서버 descriptor를 동일 후보의 단건 처리로 왕복한다", () => {
    const now = Date.parse("2026-07-14T00:00:00Z");
    const success = {
      candidateId: 7,
      candidateName: "후보 7",
      action: "delete" as const,
      reviewState: "deleted" as const,
      clientOperationId: "11111111-1111-4111-8111-111111111111",
      undo: { candidate_id: 7, token: "opaque-token" },
    };
    expect(
      parseReviewUndoHandoff(serializeReviewUndoHandoff(success, now), now),
    ).toEqual(success);
  });

  it("5분이 지난 handoff와 과거 v1 payload는 폐기한다", () => {
    const now = Date.parse("2026-07-14T00:00:00Z");
    const success = {
      candidateId: 7,
      candidateName: "후보 7",
      action: "delete" as const,
      reviewState: "deleted" as const,
      clientOperationId: "11111111-1111-4111-8111-111111111111",
      undo: { candidate_id: 7, token: "opaque-token" },
    };
    expect(
      parseReviewUndoHandoff(
        serializeReviewUndoHandoff(success, now),
        now + REVIEW_UNDO_HANDOFF_TTL_MS + 1,
      ),
    ).toBeNull();
    expect(
      parseReviewUndoHandoff(
        JSON.stringify({ version: 1, ...success }),
        now,
      ),
    ).toBeNull();
  });

  it("깨진 JSON과 후보 ID가 다른 descriptor는 폐기한다", () => {
    expect(parseReviewUndoHandoff("{")).toBeNull();
    expect(
      parseReviewUndoHandoff(
        JSON.stringify({
          version: 2,
          created_at: "2026-07-14T00:00:00Z",
          client_operation_id: "11111111-1111-4111-8111-111111111111",
          candidateId: 7,
          candidateName: "후보 7",
          action: "delete",
          reviewState: "deleted",
          undo: { candidate_id: 8, token: "opaque-token" },
        }),
      ),
    ).toBeNull();
  });
});

describe("operation marker bounded retry", () => {
  it("기대 post-state의 null marker만 150/350ms 뒤 재조회한다", async () => {
    const pending = authoritative("ignored");
    if (pending.status !== "success") throw new Error("상세 fixture 오류");
    const completed = authoritative("ignored");
    if (completed.status !== "success") throw new Error("상세 fixture 오류");
    completed.detail.list_item.last_client_operation_id = "operation-1";
    completed.detail.candidate.last_client_operation_id = "operation-1";
    const waits: number[] = [];
    let fetchCount = 0;

    const result = await waitForCandidateOperationMarker({
      initial: pending,
      candidateId: 1,
      expectedReviewState: "ignored",
      delays: [150, 350, 750],
      wait: async (milliseconds) => {
        waits.push(milliseconds);
      },
      fetchCandidateDetail: async () => {
        fetchCount += 1;
        return fetchCount === 1 ? pending.detail : completed.detail;
      },
    });

    expect(waits).toEqual([150, 350]);
    expect(fetchCount).toBe(2);
    expect(result?.status).toBe("success");
    if (result?.status === "success") {
      expect(result.detail.list_item.last_client_operation_id).toBe(
        "operation-1",
      );
    }
  });

  it("foreign marker는 기다리지 않고 즉시 종료한다", async () => {
    const foreign = authoritative("ignored");
    if (foreign.status !== "success") throw new Error("상세 fixture 오류");
    foreign.detail.list_item.last_client_operation_id = "foreign-operation";
    foreign.detail.candidate.last_client_operation_id = "foreign-operation";
    let called = false;

    const result = await waitForCandidateOperationMarker({
      initial: foreign,
      candidateId: 1,
      expectedReviewState: "ignored",
      fetchCandidateDetail: async () => {
        called = true;
        return foreign.detail;
      },
      wait: async () => {
        called = true;
      },
    });

    expect(result).toBe(foreign);
    expect(called).toBe(false);

    const needsReview = authoritative("needs_review");
    await waitForCandidateOperationMarker({
      initial: needsReview,
      candidateId: 1,
      expectedReviewState: "needs_review",
      fetchCandidateDetail: async () => {
        called = true;
        if (needsReview.status !== "success") throw new Error("상세 fixture 오류");
        return needsReview.detail;
      },
      wait: async () => {
        called = true;
      },
    });
    expect(called).toBe(false);
  });

  it("DELETE exact detail은 후보/list 양쪽의 op·revision·undo가 모두 같아야 한다", () => {
    const deleted = authoritative("deleted");
    if (deleted.status !== "success") throw new Error("상세 fixture 오류");
    const operationId = "operation-1";
    const undo = { candidate_id: 1, token: "delete-token" };
    deleted.detail.list_item.last_client_operation_id = operationId;
    deleted.detail.candidate.last_client_operation_id = operationId;
    deleted.detail.list_item.undo = undo;
    deleted.detail.candidate.undo = undo;

    const confirmed = confirmCandidateDeleteDetail({
      detail: deleted.detail,
      candidateId: 1,
      expectedRevision: 7,
      clientOperationId: operationId,
    });
    expect(confirmed).toEqual({ stateRevision: 8, undo });
    if (!confirmed) throw new Error("DELETE exact detail 확인 실패");
    expect(
      deleteResponseMatchesConfirmedDetail({
        response: {
          deleted: true,
          id: 1,
          client_operation_id: operationId,
          state_revision: 8,
          review_state: "deleted",
          undo,
        },
        confirmed,
        candidateId: 1,
        clientOperationId: operationId,
      }),
    ).toBe(true);
    expect(
      deleteResponseMatchesConfirmedDetail({
        response: {
          deleted: true,
          id: 1,
          client_operation_id: operationId,
          state_revision: 8,
          review_state: "deleted",
          undo: { candidate_id: 1, token: "mismatched-response-token" },
        },
        confirmed,
        candidateId: 1,
        clientOperationId: operationId,
      }),
    ).toBe(false);

    deleted.detail.candidate.undo = { candidate_id: 1, token: "other-token" };
    expect(
      confirmCandidateDeleteDetail({
        detail: deleted.detail,
        candidateId: 1,
        expectedRevision: 7,
        clientOperationId: operationId,
      }),
    ).toBeNull();
  });
});

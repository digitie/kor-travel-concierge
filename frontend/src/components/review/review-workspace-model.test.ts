import { describe, expect, it } from "vitest";
import type { CandidateDetail, UnmatchedCandidate } from "@/lib/api";
import { recoveryCandidateAuthority, reviewCoordinateValidation } from "./review-workspace-model";

function candidate(id: number): UnmatchedCandidate {
  return {
    id,
    video_id: `video-${id}`,
    video_title: `영상 ${id}`,
    channel_title: null,
    ai_place_name: `후보 ${id}`,
    location_hint: null,
    candidate_category: null,
    candidate_category_code: null,
    match_status: "needs_review",
    review_state: "needs_review",
    state_revision: id + 10,
    last_client_operation_id: null,
    video_is_excluded: false,
    undo: null,
    confidence_score: null,
    source_kind: "transcript",
    grounding_status: "unverified",
    created_at: "2026-07-13T00:00:00Z",
    queue_reason: "ungrounded",
    timestamp_start: null,
    is_domestic: true,
  };
}

function detail(
  id: number,
  matchStatus = "needs_review",
  reviewState = matchStatus === "ignored" ? "ignored" : "needs_review",
): CandidateDetail {
  const listItem = {
    ...candidate(id),
    match_status: matchStatus,
    review_state: reviewState as CandidateDetail["list_item"]["review_state"],
  };
  return {
    list_item: listItem,
    candidate: {
      id,
      video_id: listItem.video_id,
      source_channel_id: null,
      source_playlist_id: null,
      ai_place_name: listItem.ai_place_name,
      location_hint: listItem.location_hint,
      candidate_category: listItem.candidate_category,
      candidate_category_code: listItem.candidate_category_code,
      match_status: matchStatus,
      review_state: listItem.review_state,
      state_revision: listItem.state_revision,
      last_client_operation_id: listItem.last_client_operation_id,
      video_is_excluded: listItem.video_is_excluded,
      undo: listItem.undo,
      confidence_score: listItem.confidence_score,
      grounding_status: listItem.grounding_status,
      is_domestic: listItem.is_domestic,
      speaker_note: null,
      source_kind: listItem.source_kind,
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
}

describe("검수 상태 분리 뒤 저장·복구 권한", () => {
  const selected = candidate(1);
  const form = { name: "검수 장소", latitude: "37.5", longitude: "127", category: "", categoryCode: "" };
  const valid = { selected, form, formCandidateId: 1, selectedActionable: true, activeSelectedHit: null };
  it("다른 후보의 초안이나 비활성 상태로는 좌표가 있어도 저장하지 못한다", () => {
    expect(reviewCoordinateValidation(valid).canSave).toBe(true);
    expect(reviewCoordinateValidation({ ...valid, formCandidateId: 2 }).canSave).toBe(false);
    expect(reviewCoordinateValidation({ ...valid, selectedActionable: false }).canSave).toBe(false);
  });
  it("유효하지 않은 좌표는 차단하고 해외 좌표는 경고만 표시한다", () => {
    expect(reviewCoordinateValidation({ ...valid, form: { ...form, latitude: "not-number" } })).toMatchObject({ latInvalid: true, canSave: false });
    expect(reviewCoordinateValidation({ ...valid, form: { ...form, latitude: "48.85", longitude: "2.35" } })).toMatchObject({ coordsOutOfKorea: true, canSave: true });
  });
  function removedDetail() {
    const value = detail(1, "ignored", "ignored");
    value.list_item.undo = { candidate_id: 1, token: "test-only-recovery-descriptor" };
    value.candidate.undo = value.list_item.undo;
    return value;
  }
  it("일치하는 최신 상세만 복구에 사용할 수 있다", () => {
    const value = removedDetail();
    expect(recoveryCandidateAuthority(value.list_item, value, false, false)).toBe(value.list_item);
    expect(recoveryCandidateAuthority(value.list_item, value, false, true)).toBeNull();
  });
  it.each(["revision", "state", "identity", "descriptor"] as const)("상세의 %s 불일치는 복구를 차단한다", kind => {
    const value = removedDetail();
    if (kind === "revision") value.candidate.state_revision++;
    if (kind === "state") value.candidate.review_state = "needs_review";
    if (kind === "identity") value.candidate.id = 2;
    if (kind === "descriptor") value.list_item.undo = { candidate_id: 2, token: "test-only-invalid-descriptor" };
    expect(recoveryCandidateAuthority(value.list_item, value, false, false)).toBeNull();
  });
});

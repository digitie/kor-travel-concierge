import { describe, expect, it } from "vitest";

import type { CandidateDetail, UnmatchedCandidate } from "./api";
import {
  applyReviewListStatePatch,
  candidateMatchesReviewListState,
  DEFAULT_REVIEW_LIST_STATE,
  isReviewCandidateActionable,
  isCurrentReviewWorkflow,
  parseReviewCandidateId,
  parseReviewListState,
  reconcileReviewSearchDraft,
  REVIEW_GROUNDING_STATUSES,
  reviewCandidateMatchesStatus,
  reviewListStateHasFilters,
  reviewListStateScopeKey,
  reviewListStateToBulkFilter,
  reviewListStateToFilter,
  reviewListStateToForeignBulkFilter,
  writeReviewListState,
  DEFAULT_REVIEW_MODE,
  parseReviewMode,
  writeReviewMode,
} from "./review-list-state";

const LIST_ITEM: UnmatchedCandidate = {
  id: 42,
  video_id: "video-42",
  video_title: "제주 산책",
  channel_title: "여행 채널",
  ai_place_name: "성산일출봉",
  location_hint: "제주 서귀포",
  candidate_category: "자연",
  candidate_category_code: "01010000",
  match_status: "needs_review",
  review_state: "needs_review",
  state_revision: 7,
  last_client_operation_id: null,
  video_is_excluded: false,
  undo: null,
  confidence_score: 0.8,
  source_kind: "transcript",
  grounding_status: "verified_raw",
  created_at: "2026-07-13T00:00:00Z",
  queue_reason: "name_mismatch",
  timestamp_start: "00:12",
  is_domestic: true,
};

function detail(overrides: Partial<UnmatchedCandidate> = {}): CandidateDetail {
  const listItem = { ...LIST_ITEM, ...overrides };
  return {
    list_item: listItem,
    candidate: {
      id: listItem.id,
      video_id: listItem.video_id,
      source_channel_id: "channel-1",
      source_playlist_id: "playlist-1",
      ai_place_name: listItem.ai_place_name,
      location_hint: listItem.location_hint,
      candidate_category: listItem.candidate_category,
      candidate_category_code: listItem.candidate_category_code,
      match_status: listItem.match_status,
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
      timestamp_start: listItem.timestamp_start,
      timestamp_end: null,
      source_text: null,
    },
    video: {
      video_id: listItem.video_id,
      title: listItem.video_title,
      url: "https://www.youtube.com/watch?v=video-42",
      channel_id: "channel-1",
      channel_title: listItem.channel_title,
      source_search_query: "제주 여행",
      published_at: null,
      duration_seconds: null,
      description: null,
    },
    source_run: null,
    provider_evidence: null,
    sibling_candidates: [],
  };
}

describe("검수 목록 URL 상태", () => {
  it("유효한 URL을 서버 filter와 동일한 상태로 변환한다", () => {
    const state = parseReviewListState(
      new URLSearchParams(
        "group=channel&group_value=channel-1&q=%EC%A0%9C%EC%A3%BC&sort=newest&is_domestic=false&reason=name_mismatch&source_kind=transcript&grounding=unverified",
      ),
    );

    expect(state).toEqual({
      groupDim: "channel",
      groupValue: "channel-1",
      query: "제주",
      sort: "newest",
      isDomestic: false,
      queueReason: "name_mismatch",
      sourceKind: "transcript",
      groundingStatus: "unverified",
      status: "needs_review",
    });
    expect(reviewListStateToFilter(state)).toEqual({
      channelId: "channel-1",
      playlistId: null,
      keyword: null,
      query: "제주",
      sort: "newest",
      isDomestic: false,
      status: "needs_review",
      queueReason: "name_mismatch",
      sourceKind: "transcript",
      grounding: "unverified",
    });
  });

  it("URL membership를 pagination/sort/deep-link 없는 bulk filter로 고정한다", () => {
    const state = {
      ...DEFAULT_REVIEW_LIST_STATE,
      groupDim: "playlist" as const,
      groupValue: " playlist-1 ",
      query: " 제주 ",
      sort: "newest" as const,
      isDomestic: false,
      queueReason: "name_mismatch" as const,
      sourceKind: "transcript" as const,
      groundingStatus: "unverified" as const,
      status: "removed" as const,
    };

    const filter = reviewListStateToBulkFilter(state);

    expect(filter).toEqual({
      playlist_id: "playlist-1",
      q: "제주",
      is_domestic: false,
      status: "removed",
      reason: "name_mismatch",
      source_kind: "transcript",
      grounding: "unverified",
    });
    expect(filter).not.toHaveProperty("sort");
    expect(filter).not.toHaveProperty("cursor");
    expect(filter).not.toHaveProperty("limit");
    expect(filter).not.toHaveProperty("newer_than_id");
    expect(filter).not.toHaveProperty("candidate");
  });

  it("undefined override는 현재 false를 유지하고 null override는 국내외 전체로 바꾼다", () => {
    const state = { ...DEFAULT_REVIEW_LIST_STATE, isDomestic: false };

    expect(
      reviewListStateToBulkFilter(state, { isDomestic: undefined })
        .is_domestic,
    ).toBe(false);
    expect(
      reviewListStateToBulkFilter(state, { isDomestic: null }).is_domestic,
    ).toBeNull();
    expect(
      reviewListStateToBulkFilter(DEFAULT_REVIEW_LIST_STATE),
    ).toEqual({ is_domestic: null, status: "needs_review" });
  });

  it("값 없는 그룹 기준은 bulk membership에 포함하지 않는다", () => {
    expect(
      reviewListStateToBulkFilter({
        ...DEFAULT_REVIEW_LIST_STATE,
        groupDim: "channel",
        groupValue: null,
      }),
    ).toEqual({ is_domestic: null, status: "needs_review" });
  });

  it("현재 filter의 해외 전체 helper는 국내/removed만 덮고 기존 교집합 조건을 보존한다", () => {
    const filter = reviewListStateToForeignBulkFilter({
      ...DEFAULT_REVIEW_LIST_STATE,
      groupDim: "keyword",
      groupValue: "제주 여행",
      query: "카페",
      isDomestic: true,
      status: "removed",
      queueReason: "ambiguous",
      sourceKind: "visual",
    });

    expect(filter).toEqual({
      keyword: "제주 여행",
      q: "카페",
      is_domestic: false,
      status: "needs_review",
      reason: "ambiguous",
      source_kind: "visual",
    });
  });

  it.each(REVIEW_GROUNDING_STATUSES)(
    "grounding=%s를 다섯 상태 중 하나로 엄격하게 왕복한다",
    (groundingStatus) => {
      const state = parseReviewListState(
        new URLSearchParams(`sort=oldest&grounding=${groundingStatus}`),
      );

      expect(state.groundingStatus).toBe(groundingStatus);
      expect(
        writeReviewListState(new URLSearchParams(), state).toString(),
      ).toBe(`sort=oldest&grounding=${groundingStatus}`);
    },
  );

  it("손상된 값을 안전 기본값으로 정규화하고 candidate는 보존한다", () => {
    const current = new URLSearchParams(
      "candidate=42&sort=garbage&is_domestic=yes&group=x&group_value=bad&q=%20%EC%A0%9C%EC%A3%BC%20&reason=bad&grounding=bad",
    );
    const parsed = parseReviewListState(current);
    const canonical = writeReviewListState(current, parsed);

    expect(parsed).toEqual({ ...DEFAULT_REVIEW_LIST_STATE, query: "제주" });
    expect(canonical.toString()).toBe(
      "candidate=42&sort=oldest&q=%EC%A0%9C%EC%A3%BC",
    );
  });

  it("removed를 URL 정본으로 왕복하고 legacy ignored 링크를 removed로 정규화한다", () => {
    const removed = parseReviewListState(
      new URLSearchParams("sort=newest&status=removed"),
    );
    const legacy = parseReviewListState(
      new URLSearchParams("sort=oldest&status=ignored"),
    );

    expect(removed.status).toBe("removed");
    expect(
      writeReviewListState(new URLSearchParams(), removed).toString(),
    ).toBe("sort=newest&status=removed");
    expect(legacy.status).toBe("removed");
    expect(
      writeReviewListState(new URLSearchParams(), legacy).toString(),
    ).toBe("sort=oldest&status=removed");
  });

  it.each(["abc", "1.0", "0", "01", "2147483648", "9007199254740992"])(
    "잘못된 candidate=%s를 canonical URL에서 제거한다",
    (candidateId) => {
      const current = new URLSearchParams(`candidate=${candidateId}&sort=oldest`);

      expect(parseReviewCandidateId(current)).toBeNull();
      expect(
        writeReviewListState(current, DEFAULT_REVIEW_LIST_STATE).toString(),
      ).toBe("sort=oldest");
    },
  );

  it("PostgreSQL INTEGER 최대 후보 ID는 보존한다", () => {
    const current = new URLSearchParams("candidate=2147483647&sort=oldest");

    expect(parseReviewCandidateId(current)).toBe(2_147_483_647);
  });

  it("중복 candidate를 첫 양의 정수 하나로 canonicalize한다", () => {
    const current = new URLSearchParams(
      "candidate=42&candidate=43&sort=oldest",
    );

    expect(parseReviewCandidateId(current)).toBe(42);
    expect(
      writeReviewListState(current, DEFAULT_REVIEW_LIST_STATE).toString(),
    ).toBe("candidate=42&sort=oldest");
  });

  it("중복 candidate 중 첫 유효 safe integer를 선택한다", () => {
    const current = new URLSearchParams(
      "candidate=abc&candidate=42&candidate=43&sort=oldest",
    );

    expect(parseReviewCandidateId(current)).toBe(42);
    expect(
      writeReviewListState(current, DEFAULT_REVIEW_LIST_STATE).toString(),
    ).toBe("candidate=42&sort=oldest");
  });

  it("필터 해제에도 oldest 정본과 딥링크를 유지한다", () => {
    const canonical = writeReviewListState(
      new URLSearchParams(
        "candidate=42&q=test&is_domestic=true&grounding=missing",
      ),
      DEFAULT_REVIEW_LIST_STATE,
    );

    expect(canonical.toString()).toBe("candidate=42&sort=oldest");
  });

  it("그룹 기준을 먼저 고른 중간 상태를 보존하되 서버 filter는 적용하지 않는다", () => {
    const state = parseReviewListState(
      new URLSearchParams("sort=oldest&group=channel"),
    );

    expect(state.groupDim).toBe("channel");
    expect(state.groupValue).toBeNull();
    expect(writeReviewListState(new URLSearchParams(), state).toString()).toBe(
      "sort=oldest&group=channel",
    );
    expect(reviewListStateToFilter(state).channelId).toBeNull();
    expect(candidateMatchesReviewListState(detail(), state)).toBe(true);
  });

  it("URL rerender 전 연속 patch도 앞선 검색 조건을 유실하지 않는다", () => {
    const first = applyReviewListStatePatch(
      new URLSearchParams("candidate=42&sort=oldest"),
      DEFAULT_REVIEW_LIST_STATE,
      { query: "제주" },
    );
    const second = applyReviewListStatePatch(first.params, first.state, {
      sort: "newest",
    });
    const third = applyReviewListStatePatch(second.params, second.state, {
      isDomestic: false,
    });
    const fourth = applyReviewListStatePatch(third.params, third.state, {
      groundingStatus: "missing",
    });

    expect(fourth.params.toString()).toBe(
      "candidate=42&sort=newest&q=%EC%A0%9C%EC%A3%BC&is_domestic=false&grounding=missing",
    );

    const candidateCleared = new URLSearchParams(fourth.params);
    candidateCleared.delete("candidate");
    const fifth = applyReviewListStatePatch(candidateCleared, fourth.state, {
      queueReason: "ambiguous",
    });
    expect(fifth.params.toString()).toBe(
      "sort=newest&q=%EC%A0%9C%EC%A3%BC&is_domestic=false&reason=ambiguous&grounding=missing",
    );
  });

  it("별도 객체로 다시 만들어진 A scope도 identity가 아닌 의미로 같게 판정한다", () => {
    const first = { ...DEFAULT_REVIEW_LIST_STATE, query: "제주" };
    const second = { ...DEFAULT_REVIEW_LIST_STATE, query: "제주" };

    expect(first).not.toBe(second);
    expect(reviewListStateScopeKey(first)).toBe(reviewListStateScopeKey(second));
    expect(
      reviewListStateScopeKey({ ...second, query: "부산" }),
    ).not.toBe(reviewListStateScopeKey(first));
    expect(
      reviewListStateScopeKey({
        ...second,
        groundingStatus: "verified_raw",
      }),
    ).not.toBe(reviewListStateScopeKey(first));
  });

  it("grounding scope가 A→B→A로 돌아오면 새 A는 처음 A와만 같게 판정한다", () => {
    const firstA = {
      ...DEFAULT_REVIEW_LIST_STATE,
      groundingStatus: "verified_raw" as const,
    };
    const middleB = { ...firstA, groundingStatus: "missing" as const };
    const latestA = { ...middleB, groundingStatus: "verified_raw" as const };

    expect(reviewListStateScopeKey(middleB)).not.toBe(
      reviewListStateScopeKey(firstA),
    );
    expect(reviewListStateScopeKey(latestA)).toBe(
      reviewListStateScopeKey(firstA),
    );
  });

  it("grounding만 선택해도 활성 filter로 판정하고 해제 시 기본 scope로 돌아간다", () => {
    const filtered = {
      ...DEFAULT_REVIEW_LIST_STATE,
      groundingStatus: "legacy_unknown" as const,
    };

    expect(reviewListStateHasFilters(filtered)).toBe(true);
    expect(reviewListStateHasFilters(DEFAULT_REVIEW_LIST_STATE)).toBe(false);
    expect(
      writeReviewListState(
        new URLSearchParams("candidate=42&grounding=legacy_unknown"),
        DEFAULT_REVIEW_LIST_STATE,
      ).toString(),
    ).toBe("candidate=42&sort=oldest");
  });
});

describe("page 밖 검수 후보 분류", () => {
  it("URL control patch가 만든 즉시 상태로 page 밖 후보를 다시 분류한다", () => {
    const initial = {
      ...DEFAULT_REVIEW_LIST_STATE,
      groupDim: "channel" as const,
      groupValue: "channel-1",
      query: "서귀포",
    };
    const changed = applyReviewListStatePatch(
      writeReviewListState(new URLSearchParams("candidate=42"), initial),
      initial,
      { query: "부산" },
    );

    expect(candidateMatchesReviewListState(detail(), initial)).toBe(true);
    expect(candidateMatchesReviewListState(detail(), changed.state)).toBe(false);
    expect(changed.params.get("candidate")).toBe("42");
    expect(changed.params.get("q")).toBe("부산");
  });

  it("상세 provenance와 목록 scalar로 현재 filter 포함 여부를 정확히 판정한다", () => {
    const state = {
      ...DEFAULT_REVIEW_LIST_STATE,
      groupDim: "channel" as const,
      groupValue: "channel-1",
      query: "서귀포",
      isDomestic: true,
      queueReason: "name_mismatch" as const,
      sourceKind: "transcript" as const,
      groundingStatus: "verified_raw" as const,
    };

    expect(candidateMatchesReviewListState(detail(), state)).toBe(true);
    expect(
      candidateMatchesReviewListState(detail(), {
        ...state,
        groupValue: "channel-2",
      }),
    ).toBe(false);
    expect(
      candidateMatchesReviewListState(detail(), { ...state, query: "부산" }),
    ).toBe(false);
    expect(
      candidateMatchesReviewListState(
        detail({ grounding_status: "unverified" }),
        state,
      ),
    ).toBe(false);
  });

  it("재생목록·검색어 provenance도 page 조회 없이 판정한다", () => {
    expect(
      candidateMatchesReviewListState(detail(), {
        ...DEFAULT_REVIEW_LIST_STATE,
        groupDim: "playlist",
        groupValue: "playlist-1",
      }),
    ).toBe(true);
    expect(
      candidateMatchesReviewListState(detail(), {
        ...DEFAULT_REVIEW_LIST_STATE,
        groupDim: "keyword",
        groupValue: "제주 여행",
      }),
    ).toBe(true);
    expect(
      candidateMatchesReviewListState(detail(), {
        ...DEFAULT_REVIEW_LIST_STATE,
        groupDim: "keyword",
        groupValue: "부산 여행",
      }),
    ).toBe(false);
  });

  it("상태가 바뀐 direct detail은 처리 불가로 판정한다", () => {
    const processed = detail({
      match_status: "ignored",
      review_state: "ignored",
    });

    expect(isReviewCandidateActionable(processed.list_item)).toBe(false);
    expect(
      candidateMatchesReviewListState(processed, DEFAULT_REVIEW_LIST_STATE),
    ).toBe(false);
  });

  it("removed는 ignored와 deleted를 함께 포함하고 underlying needs_review 삭제 후보를 처리 불가로 본다", () => {
    const ignored = detail({
      match_status: "ignored",
      review_state: "ignored",
    });
    const deleted = detail({
      match_status: "needs_review",
      review_state: "deleted",
    });
    const removedState = {
      ...DEFAULT_REVIEW_LIST_STATE,
      status: "removed" as const,
    };

    expect(reviewCandidateMatchesStatus(ignored.list_item, "removed")).toBe(
      true,
    );
    expect(reviewCandidateMatchesStatus(deleted.list_item, "removed")).toBe(
      true,
    );
    expect(candidateMatchesReviewListState(ignored, removedState)).toBe(true);
    expect(candidateMatchesReviewListState(deleted, removedState)).toBe(true);
    expect(isReviewCandidateActionable(deleted.list_item)).toBe(false);
    expect(
      candidateMatchesReviewListState(deleted, DEFAULT_REVIEW_LIST_STATE),
    ).toBe(false);
  });

  it("Unicode 후보명은 자기 자신 검색에서 목록에 포함한다", () => {
    expect(
      candidateMatchesReviewListState(detail({ ai_place_name: "Straße" }), {
        ...DEFAULT_REVIEW_LIST_STATE,
        query: "Straße",
      }),
    ).toBe(true);
  });
});

describe("검수 검색 draft 동기화", () => {
  it("늦게 도착한 자기 commit은 그 사이 입력한 최신 draft를 덮지 않는다", () => {
    expect(
      reconcileReviewSearchDraft({
        draft: "제주 여행",
        previousValue: "",
        value: "제주",
        pendingValue: "제주",
      }),
    ).toEqual({ draft: "제주 여행", pendingValue: null });
  });

  it("pending commit이 아닌 back/forward value는 draft에 반영한다", () => {
    expect(
      reconcileReviewSearchDraft({
        draft: "제주 여행",
        previousValue: "제주 여행",
        value: "부산",
        pendingValue: null,
      }),
    ).toEqual({ draft: "부산", pendingValue: null });
  });
});

describe("검수 workflow 세대", () => {
  it("후보와 scope가 A→B→A로 돌아와도 과거 command를 거부한다", () => {
    expect(
      isCurrentReviewWorkflow({
        commandCandidateId: 42,
        commandQueueScope: "scope-a",
        commandEpoch: 7,
        currentCandidateId: 42,
        currentQueueScope: "scope-a",
        currentEpoch: 9,
      }),
    ).toBe(false);
    expect(
      isCurrentReviewWorkflow({
        commandCandidateId: 42,
        commandQueueScope: "scope-a",
        commandEpoch: 9,
        currentCandidateId: 42,
        currentQueueScope: "scope-a",
        currentEpoch: 9,
      }),
    ).toBe(true);
  });
});

describe("review mode (T-187)", () => {
  it("기본 모드는 처리 모드(triage)다", () => {
    expect(DEFAULT_REVIEW_MODE).toBe("triage");
    expect(parseReviewMode(new URLSearchParams())).toBe("triage");
    expect(parseReviewMode(new URLSearchParams("mode=nonsense"))).toBe("triage");
  });

  it("mode=table만 table로 해석한다", () => {
    expect(parseReviewMode(new URLSearchParams("mode=table"))).toBe("table");
  });

  it("table은 URL에 명시하고 triage(기본)는 파라미터를 제거한다", () => {
    expect(writeReviewMode(new URLSearchParams("sort=oldest"), "table").toString()).toBe(
      "sort=oldest&mode=table",
    );
    expect(
      writeReviewMode(new URLSearchParams("sort=oldest&mode=table"), "triage").toString(),
    ).toBe("sort=oldest");
  });

  it("모드는 목록 상태와 독립적이라 filter rewrite에도 보존된다", () => {
    const withMode = writeReviewMode(new URLSearchParams(), "table");
    const next = writeReviewListState(withMode, {
      ...DEFAULT_REVIEW_LIST_STATE,
      isDomestic: false,
    });
    expect(parseReviewMode(next)).toBe("table");
    expect(next.get("is_domestic")).toBe("false");
  });
});

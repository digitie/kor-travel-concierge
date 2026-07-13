import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteCandidate,
  executeReviewBulk,
  groupThemeItems,
  listRunQueue,
  listUnmatchedCandidatesPage,
  previewReviewBulk,
  REVIEW_BULK_CANDIDATE_ID_MAX,
  REVIEW_BULK_SELECTION_MAX,
  reopenCandidate,
  resolveCandidate,
  restartRun,
  RUN_HISTORY_REFETCH_INTERVAL_MS,
  RUN_QUEUE_OBSERVER_OPTIONS,
  RUN_QUEUE_QUERY_KEY,
  RUN_QUEUE_REFETCH_INTERVAL_MS,
  RUN_QUEUE_STALE_TIME_MS,
  runQueueRefetchDelay,
  runQueueRefetchInterval,
  stopRun,
  type RunQueueSnapshot,
  type RestartRunResult,
  type ReviewBulkExecuteResult,
  type ReviewBulkFilterSnapshot,
  type ReviewBulkPreview,
  type ReviewBulkPreviewInput,
  type StopRunResult,
  type ThemeSummaryItem,
} from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("groupThemeItems", () => {
  it("flat theme page를 기존 세 그룹 계약으로 복원한다", () => {
    const items: ThemeSummaryItem[] = [
      {
        kind: "channel",
        value: "c1",
        title: "채널",
        poi_count: 3,
        first_mapping_id: 1,
        latest_mapping_id: 9,
      },
      {
        kind: "playlist",
        value: "p1",
        title: "재생목록",
        poi_count: 2,
        first_mapping_id: 2,
        latest_mapping_id: 8,
      },
      {
        kind: "keyword",
        value: "부산 여행",
        title: "부산 여행",
        poi_count: 1,
        first_mapping_id: 3,
        latest_mapping_id: 7,
      },
    ];

    expect(groupThemeItems(items)).toEqual({
      channels: [{ value: "c1", title: "채널", poi_count: 3 }],
      playlists: [{ value: "p1", title: "재생목록", poi_count: 2 }],
      keywords: [{ value: "부산 여행", title: "부산 여행", poi_count: 1 }],
    });
  });
});

describe("listUnmatchedCandidatesPage", () => {
  it("검수 검색·정렬·국내 여부·사유·출처·grounding을 cursor filter query로 직렬화한다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [],
          next_cursor: null,
          has_more: false,
          total: 0,
          newest_id: null,
          newer_than: 0,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listUnmatchedCandidatesPage(
      {
        channelId: "channel-1",
        playlistId: "playlist-1",
        keyword: "제주 여행",
        query: "성산일출봉",
        sort: "oldest",
        isDomestic: false,
        status: "needs_review",
        queueReason: "name_mismatch",
        sourceKind: "transcript",
        grounding: "unverified",
      },
      { limit: 10, cursor: "cursor-1", newerThanId: 7 },
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/destinations/unmatched?limit=10&cursor=cursor-1&newer_than_id=7&channel_id=channel-1&playlist_id=playlist-1&keyword=%EC%A0%9C%EC%A3%BC+%EC%97%AC%ED%96%89&q=%EC%84%B1%EC%82%B0%EC%9D%BC%EC%B6%9C%EB%B4%89&sort=oldest&is_domestic=false&status=needs_review&reason=name_mismatch&source_kind=transcript&grounding=unverified",
      expect.objectContaining({
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("복구 목록 status=removed를 서버 query로 직렬화한다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [],
          next_cursor: null,
          has_more: false,
          total: 0,
          newest_id: null,
          newer_than: 0,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listUnmatchedCandidatesPage({ status: "removed" }, { limit: 300 });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/destinations/unmatched?limit=300&status=removed",
      expect.objectContaining({
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
});

describe("검수 후보 bulk API", () => {
  const previewResponse: ReviewBulkPreview = {
    operation_id: "operation-1",
    confirmation_token: "opaque-confirmation-token",
    expires_at: "2026-07-14T12:10:00Z",
    total: 2,
    chunk_size: 100,
  };

  it("유효한 filter 상태와 action 조합을 보존한다", () => {
    const ignoreInput = {
      action: "ignore",
      scope: {
        kind: "filter",
        filter: { is_domestic: false, status: "needs_review" },
      },
    } satisfies ReviewBulkPreviewInput;
    const reopenInput = {
      action: "reopen",
      scope: {
        kind: "filter",
        filter: { is_domestic: null, status: "removed" },
      },
    } satisfies ReviewBulkPreviewInput;
    expect([
      ignoreInput.scope.filter.status,
      reopenInput.scope.filter.status,
    ]).toEqual(["needs_review", "removed"]);
  });

  it("선택 범위의 중복 ID를 제거하고 서버 snake_case 계약으로 보낸다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(previewResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await previewReviewBulk({
      action: "delete",
      scope: { kind: "selection", candidateIds: [42, 7, 42] },
    });

    expect(result).toEqual(previewResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/destinations/unmatched/bulk/preview",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          action: "delete",
          scope: { kind: "selection", candidate_ids: [42, 7] },
        }),
      }),
    );
  });

  it("filter membership만 열거해 false를 보존하고 목록 cursor/sort를 차단한다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(previewResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const runtimeFilter = {
      channel_id: " channel-1 ",
      q: " 제주 ",
      is_domestic: false,
      status: "needs_review",
      reason: "foreign",
      sort: "newest",
      cursor: "cursor-must-not-leak",
      newer_than_id: 99,
      limit: 200,
      candidate: 42,
    } as ReviewBulkFilterSnapshot<"needs_review"> & Record<string, unknown>;

    await previewReviewBulk({
      action: "ignore",
      scope: { kind: "filter", filter: runtimeFilter },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/destinations/unmatched/bulk/preview",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          action: "ignore",
          scope: {
            kind: "filter",
            filter: {
              channel_id: "channel-1",
              q: "제주",
              is_domestic: false,
              status: "needs_review",
              reason: "foreign",
            },
          },
        }),
      }),
    );
  });

  it("국내외 전체 filter는 is_domestic null을 누락하지 않고 보낸다", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(previewResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await previewReviewBulk({
      action: "ignore",
      scope: {
        kind: "filter",
        filter: { is_domestic: null, status: "needs_review" },
      },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/destinations/unmatched/bulk/preview",
      expect.objectContaining({
        body: JSON.stringify({
          action: "ignore",
          scope: {
            kind: "filter",
            filter: { is_domestic: null, status: "needs_review" },
          },
        }),
      }),
    );
  });

  it("빈 선택, 잘못된 ID, 500개 초과 선택은 fetch 전에 거부한다", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const oversized = Array.from(
      { length: REVIEW_BULK_SELECTION_MAX + 1 },
      (_, index) => index + 1,
    );

    await expect(
      previewReviewBulk({
        action: "delete",
        scope: { kind: "selection", candidateIds: [] },
      }),
    ).rejects.toThrow("한 개 이상");
    await expect(
      previewReviewBulk({
        action: "delete",
        scope: { kind: "selection", candidateIds: [0] },
      }),
    ).rejects.toThrow("양의 정수");
    await expect(
      previewReviewBulk({
        action: "delete",
        scope: {
          kind: "selection",
          candidateIds: [REVIEW_BULK_CANDIDATE_ID_MAX + 1],
        },
      }),
    ).rejects.toThrow("양의 정수");
    await expect(
      previewReviewBulk({
        action: "delete",
        scope: { kind: "selection", candidateIds: oversized },
      }),
    ).rejects.toThrow(`최대 ${REVIEW_BULK_SELECTION_MAX}개`);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("response-loss 재시도는 같은 operation/request/cursor body를 바꾸지 않는다", async () => {
    const executeResponse: ReviewBulkExecuteResult = {
      operation_id: "operation-1",
      request_id: "11111111-1111-4111-8111-111111111111",
      processed: 2,
      succeeded: 2,
      conflicts: [],
      failed: [],
      remaining: 0,
      next_cursor: null,
      complete: true,
    };
    const fetchMock = vi.fn().mockImplementation(
      async () =>
        new Response(JSON.stringify(executeResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const input = {
      operationId: "operation-1",
      confirmationToken: "opaque-confirmation-token",
      cursor: "cursor-1",
      requestId: "11111111-1111-4111-8111-111111111111",
    };

    await executeReviewBulk(input);
    await executeReviewBulk(input);

    const expectedBody = JSON.stringify({
      operation_id: "operation-1",
      confirmation_token: "opaque-confirmation-token",
      cursor: "cursor-1",
      request_id: "11111111-1111-4111-8111-111111111111",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/v1/destinations/unmatched/bulk/execute",
      expect.objectContaining({ method: "POST", body: expectedBody }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/destinations/unmatched/bulk/execute",
      expect.objectContaining({ method: "POST", body: expectedBody }),
    );
  });
});

describe("검수 후보 상태 전이 API", () => {
  it("resolve에 필수 state revision을 snake_case로 보낸다", async () => {
    const clientOperationId = "11111111-1111-4111-8111-111111111111";
    const responseBody = {
      status: "resolved",
      client_operation_id: clientOperationId,
      candidate: {
        id: 42,
        video_id: "video-42",
        ai_place_name: "후보 42",
        match_status: "ignored",
        review_state: "ignored",
        state_revision: 8,
        last_client_operation_id: clientOperationId,
        video_is_excluded: false,
        undo: { candidate_id: 42, token: "opaque-undo-42" },
        matched_place_id: null,
        feature_export_status: "rejected",
      },
      place: null,
      mapping_id: null,
      undo: { candidate_id: 42, token: "opaque-undo-42" },
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await resolveCandidate(42, {
      action: "ignore",
      expectedRevision: 7,
      clientOperationId,
      reviewNote: "검수 페이지 제외",
    });

    expect(result).toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/destinations/unmatched/42/resolve",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          action: "ignore",
          expected_revision: 7,
          client_operation_id: clientOperationId,
          review_note: "검수 페이지 제외",
        }),
      }),
    );
  });

  it("DELETE revision과 사유를 query로 보내고 서버 undo descriptor를 보존한다", async () => {
    const clientOperationId = "22222222-2222-4222-8222-222222222222";
    const responseBody = {
      deleted: true,
      id: 42,
      client_operation_id: clientOperationId,
      state_revision: 8,
      review_state: "deleted",
      undo: { candidate_id: 42, token: "opaque-delete-42" },
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await deleteCandidate(
      42,
      7,
      clientOperationId,
      " 검수 오류 ",
    );

    expect(result).toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/destinations/candidates/42?expected_revision=7&client_operation_id=${clientOperationId}&reason=%EA%B2%80%EC%88%98+%EC%98%A4%EB%A5%98`,
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("reopen은 descriptor candidate 경로에 opaque token만 전송한다", async () => {
    const responseBody = {
      status: "reopened",
      reopened_from: "deleted",
      candidate: {
        id: 42,
        video_id: "video-42",
        ai_place_name: "후보 42",
        match_status: "needs_review",
        review_state: "needs_review",
        state_revision: 9,
        last_client_operation_id: null,
        video_is_excluded: false,
        matched_place_id: null,
        feature_export_status: "pending",
      },
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await reopenCandidate({
      candidate_id: 42,
      token: "opaque-delete-42",
    });

    expect(result).toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/destinations/unmatched/42/reopen",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ undo_token: "opaque-delete-42" }),
      }),
    );
  });
});

describe("listRunQueue", () => {
  it("통합 queue endpoint를 한 번 호출해 attention 포함 snapshot을 반환한다", async () => {
    const responseBody: RunQueueSnapshot = {
      items: [],
      open_attention_count: 2,
      running_count: 3,
      pending_count: 4,
      has_more: true,
      user_job_types: ["harvest", "poi_batch"],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await listRunQueue();

    expect(result).toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/runs/queue",
      expect.objectContaining({
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("모든 observer가 공유할 query key와 10초 정책을 고정한다", () => {
    expect(RUN_QUEUE_QUERY_KEY).toEqual(["run-queue"]);
    expect(RUN_QUEUE_STALE_TIME_MS).toBe(10_000);
    expect(RUN_QUEUE_REFETCH_INTERVAL_MS).toBe(10_000);
    expect(RUN_HISTORY_REFETCH_INTERVAL_MS).toBe(60_000);
    expect(RUN_QUEUE_OBSERVER_OPTIONS).toEqual({
      staleTime: 10_000,
      refetchOnMount: false,
      retryOnMount: false,
    });
    expect(runQueueRefetchDelay(5_000, 7_000)).toBe(8_000);
    expect(runQueueRefetchDelay(5_000, 16_000)).toBe(1);
    expect(
      runQueueRefetchInterval(
        {
          fetchStatus: "fetching",
          dataUpdatedAt: 5_000,
          errorUpdatedAt: 0,
        },
        16_000,
      ),
    ).toBe(false);
    expect(
      runQueueRefetchInterval(
        {
          fetchStatus: "paused",
          dataUpdatedAt: 5_000,
          errorUpdatedAt: 15_000,
        },
        16_000,
      ),
    ).toBe(false);
    expect(
      runQueueRefetchInterval(
        {
          fetchStatus: "idle",
          dataUpdatedAt: 5_000,
          errorUpdatedAt: 15_000,
        },
        16_000,
      ),
    ).toBe(9_000);
  });
});

describe("restartRun", () => {
  it("재시작 lineage와 멱등 생성 여부를 정확한 응답 계약으로 반환한다", async () => {
    const responseBody: RestartRunResult = {
      job_id: "42",
      state: "pending",
      restart_of_run_id: "7",
      created: false,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result: RestartRunResult = await restartRun("7");

    expect(result).toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/runs/7/restart",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
});

describe("stopRun", () => {
  it("협조적 중지 응답의 실제 경량 계약을 반환한다", async () => {
    const responseBody: StopRunResult = {
      job_id: "42",
      state: "running",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await stopRun("42");

    expect(result).toEqual(responseBody);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/runs/42/stop",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
});

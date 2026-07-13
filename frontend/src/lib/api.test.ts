import { afterEach, describe, expect, it, vi } from "vitest";

import {
  groupThemeItems,
  listRunQueue,
  listUnmatchedCandidatesPage,
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

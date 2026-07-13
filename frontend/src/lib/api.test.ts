import { afterEach, describe, expect, it, vi } from "vitest";

import {
  groupThemeItems,
  listUnmatchedCandidatesPage,
  restartRun,
  stopRun,
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
  it("검수 사유와 출처를 cursor filter query로 직렬화한다", async () => {
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
        queueReason: "name_mismatch",
        sourceKind: "transcript",
      },
      { limit: 10, cursor: "cursor-1", newerThanId: 7 },
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/destinations/unmatched?limit=10&cursor=cursor-1&newer_than_id=7&channel_id=channel-1&playlist_id=playlist-1&keyword=%EC%A0%9C%EC%A3%BC+%EC%97%AC%ED%96%89&reason=name_mismatch&source_kind=transcript",
      expect.objectContaining({
        headers: { "Content-Type": "application/json" },
      }),
    );
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

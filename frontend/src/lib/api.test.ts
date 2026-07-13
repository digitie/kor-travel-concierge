import { afterEach, describe, expect, it, vi } from "vitest";

import {
  groupThemeItems,
  listUnmatchedCandidatesPage,
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

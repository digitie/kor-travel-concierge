import { describe, expect, it } from "vitest";

import { groupThemeItems, type ThemeSummaryItem } from "./api";

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

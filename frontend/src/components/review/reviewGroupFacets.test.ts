import { describe, expect, it } from "vitest";

import type { ReviewSourceFacets } from "@/lib/api";
import { groupOptions, groupValueLabel } from "./reviewGroupFacets";

const FACETS: ReviewSourceFacets = {
  channels: [
    { value: "UC-a", label: "알파 채널", candidate_count: 3 },
    { value: "UC-b", label: "베타 채널", candidate_count: 1 },
  ],
  playlists: [{ value: "PL-1", label: "재생목록 1", candidate_count: 2 }],
  keywords: [{ value: "부산 여행", label: "부산 여행", candidate_count: 5 }],
};

describe("groupOptions", () => {
  it("차원별로 {value,label,count(=candidate_count)}를 반환한다", () => {
    expect(groupOptions("channel", FACETS)).toEqual([
      { value: "UC-a", label: "알파 채널", count: 3 },
      { value: "UC-b", label: "베타 채널", count: 1 },
    ]);
    expect(groupOptions("keyword", FACETS)).toEqual([
      { value: "부산 여행", label: "부산 여행", count: 5 },
    ]);
    expect(groupOptions("none", FACETS)).toEqual([]);
    expect(groupOptions("channel", undefined)).toEqual([]);
  });
});

describe("groupValueLabel", () => {
  it("facet에 있으면 라벨과 count를 함께 보인다", () => {
    expect(groupValueLabel("channel", "UC-a", FACETS)).toBe("알파 채널 (3)");
  });

  it("현재 filter로 facet에서 사라진 딥링크 groupValue는 raw 값으로 fallback한다", () => {
    // 공백이 아니라 원래 groupValue를 라벨로 표시해야 트리거가 비지 않는다.
    expect(groupValueLabel("channel", "UC-gone", FACETS)).toBe("UC-gone");
  });

  it("facet 미로딩(undefined)이어도 raw 값으로 fallback한다", () => {
    expect(groupValueLabel("channel", "UC-a", undefined)).toBe("UC-a");
  });

  it("빈 라벨 facet도 raw 값으로 fallback한다", () => {
    const blankLabel: ReviewSourceFacets = {
      channels: [{ value: "UC-a", label: "   ", candidate_count: 2 }],
      playlists: [],
      keywords: [],
    };
    expect(groupValueLabel("channel", "UC-a", blankLabel)).toBe("UC-a");
  });

  it("값이 없으면 빈 문자열이다", () => {
    expect(groupValueLabel("channel", null, FACETS)).toBe("");
  });
});

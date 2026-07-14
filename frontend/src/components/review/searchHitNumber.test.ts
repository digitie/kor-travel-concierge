import { describe, expect, it } from "vitest";

import type { PlaceSearchHit, PlaceSearchProvider } from "@/lib/api";
import {
  searchHitShortcutNumber,
  selectableSearchHits,
} from "./searchHitNumber";

function hit(
  name: string,
  overrides: Partial<PlaceSearchHit> = {},
): PlaceSearchHit {
  return {
    provider: "kakao" as PlaceSearchProvider,
    native_id: name,
    name,
    address: null,
    road_address: null,
    latitude: 37.5,
    longitude: 127.0,
    category: null,
    storage_allowed: true,
    storage_block_reason: null,
    ...overrides,
  };
}

describe("selectableSearchHits", () => {
  it("좌표 없는 hit과 저장 불가(google/미허용) hit을 제외하고 순서를 유지한다", () => {
    const withCoords1 = hit("좌표1");
    const noCoords = hit("좌표없음", { latitude: null, longitude: null });
    const google = hit("구글", { provider: "google" as PlaceSearchProvider });
    const notAllowed = hit("미허용", { storage_allowed: false });
    const withCoords2 = hit("좌표2");
    const all = [withCoords1, noCoords, google, notAllowed, withCoords2];

    expect(selectableSearchHits(all)).toEqual([withCoords1, withCoords2]);
  });
});

describe("searchHitShortcutNumber", () => {
  it("선택 가능 hit은 selectable 목록 index+1을 서수로 준다(지도 placeId와 동일)", () => {
    const a = hit("a");
    const b = hit("b");
    const c = hit("c");
    const selectable = [a, b, c];
    expect(searchHitShortcutNumber(selectable, a, true)).toBe(1);
    expect(searchHitShortcutNumber(selectable, b, true)).toBe(2);
    expect(searchHitShortcutNumber(selectable, c, true)).toBe(3);
    // 지도 번호(mapHitEntries의 placeId = index+1)와 정확히 일치한다.
    selectable.forEach((entry, index) => {
      expect(searchHitShortcutNumber(selectable, entry, true)).toBe(index + 1);
    });
  });

  it("선택 불가 행(좌표 없음 등)에는 배지·단축키 번호를 붙이지 않는다", () => {
    const a = hit("a");
    const noCoords = hit("좌표없음", { latitude: null, longitude: null });
    const selectable = selectableSearchHits([a, noCoords]);
    // 좌표 없는 행은 selectable=false라 목록에 있어도 번호 없음.
    expect(searchHitShortcutNumber(selectable, noCoords, false)).toBeNull();
    expect(searchHitShortcutNumber(selectable, a, true)).toBe(1);
  });

  it("selectable 목록에 없는 hit이나 10번째 이상은 null이다", () => {
    const items = Array.from({ length: 10 }, (_, index) => hit(`h${index}`));
    // 9번째까지만 번호(1–9), 10번째는 null.
    expect(searchHitShortcutNumber(items, items[8], true)).toBe(9);
    expect(searchHitShortcutNumber(items, items[9], true)).toBeNull();
    const outsider = hit("outsider");
    expect(searchHitShortcutNumber(items, outsider, true)).toBeNull();
    expect(searchHitShortcutNumber(undefined, items[0], true)).toBeNull();
  });
});

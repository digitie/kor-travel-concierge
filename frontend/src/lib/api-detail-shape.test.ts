import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getCandidateDetail,
  getPlaceDetail,
  isCandidateDetailShape,
  isPlaceDetailShape,
  MalformedResponseError,
} from "./api";

// 2026-11-23 격리 점검: 상세 응답이 `[]`이면 상세 화면이 TypeError로 죽어 셸까지 사라졌다.
const candidate = {
  list_item: { id: 1 },
  candidate: { id: 1, timestamp_start: null },
  video: null,
  source_run: null,
  provider_evidence: null,
  sibling_candidates: [],
};
const place = { place: { place_id: 1, road_address: null }, stats: { mention_count: 0 }, source_videos: [{ mentions: [] }] };

afterEach(() => vi.unstubAllGlobals());

function stubJson(body: unknown) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } })));
}

describe("상세 응답 모양 가드", () => {
  it("계약 모양은 통과시킨다", () => {
    expect(isCandidateDetailShape(candidate)).toBe(true);
    expect(isPlaceDetailShape(place)).toBe(true);
  });

  it.each([[[]], [null], ["x"], [{}], [{ ...candidate, candidate: [] }], [{ ...candidate, sibling_candidates: null }], [{ ...candidate, video: [] }]])(
    "후보 상세가 계약 모양이 아니면 거부한다 %#",
    (body) => expect(isCandidateDetailShape(body)).toBe(false),
  );

  it.each([[[]], [{}], [{ ...place, place: null }], [{ ...place, source_videos: {} }], [{ ...place, source_videos: [{}] }], [{ ...place, stats: [] }]])(
    "장소 상세가 계약 모양이 아니면 거부한다 %#",
    (body) => expect(isPlaceDetailShape(body)).toBe(false),
  );

  it("잘못된 응답은 화면이 다룰 수 있는 오류로 바꾼다", async () => {
    stubJson([]);
    await expect(getCandidateDetail(1)).rejects.toBeInstanceOf(MalformedResponseError);
    stubJson([]);
    await expect(getPlaceDetail(1)).rejects.toThrow("장소 상세 응답 형식이 올바르지 않습니다");
    stubJson(candidate);
    await expect(getCandidateDetail(1)).resolves.toEqual(candidate);
  });
});

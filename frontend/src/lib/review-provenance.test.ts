import { describe, expect, it } from "vitest";

import { ApiRequestError, type PlaceSearchHit } from "./api";
import {
  buildCreatePlaceResolution,
  isPlaceHitStorageAllowed,
  isSelectedHitModified,
  parseNearbyPlaceConflict,
  type SelectedPlaceHit,
} from "./review-provenance";

const kakaoHit: PlaceSearchHit = {
  provider: "kakao",
  native_id: "kakao-42",
  name: "월정리 해변",
  address: "제주 제주시 구좌읍 월정리 1",
  road_address: "제주 제주시 해맞이해안로 1",
  latitude: 33.556,
  longitude: 126.795,
  category: "여행 > 관광명소",
  storage_allowed: true,
  storage_block_reason: null,
};

const selected: SelectedPlaceHit = {
  candidateId: 7,
  hit: kakaoHit,
  query: "제주 월정리 해변",
  searchedAt: "2026-07-13T01:00:00Z",
  selectedAt: "2026-07-13T01:00:03Z",
};

describe("검수 선택 provenance", () => {
  it("provider 원본과 최종 수정값을 분리해 resolve 입력을 만든다", () => {
    const input = buildCreatePlaceResolution(
      {
        name: "월정리해수욕장",
        latitude: "33.5561",
        longitude: "126.7951",
        category: "자연관광지",
        categoryCode: "01050100",
      },
      selected,
    );

    expect(input).toMatchObject({
      action: "create_place",
      correctedName: "월정리해수욕장",
      officialAddress: kakaoHit.address,
      roadAddress: kakaoHit.road_address,
      apiSource: "kakao",
      selectedHit: {
        provider: "kakao",
        native_id: "kakao-42",
        query: "제주 월정리 해변",
        searched_at: "2026-07-13T01:00:00Z",
        selected_at: "2026-07-13T01:00:03Z",
        name: "월정리 해변",
      },
    });
    expect(isSelectedHitModified({
      name: "월정리해수욕장",
      latitude: "33.5561",
      longitude: "126.7951",
      category: "자연관광지",
      categoryCode: "01050100",
    }, selected)).toBe(true);
  });

  it("직접 입력은 manual이며 provider evidence를 만들지 않는다", () => {
    const input = buildCreatePlaceResolution(
      {
        name: "직접 입력 장소",
        latitude: "37.5",
        longitude: "127",
        category: "",
        categoryCode: "",
      },
      null,
    );
    expect(input.apiSource).toBe("manual");
    expect(input.selectedHit).toBeUndefined();
    expect(input.officialAddress).toBeUndefined();
  });

  it("Google hit은 capability 값과 무관하게 저장을 차단한다", () => {
    expect(
      isPlaceHitStorageAllowed({
        ...kakaoHit,
        provider: "google",
        storage_allowed: true,
      }),
    ).toBe(false);
  });

  it("409 nearby detail을 사용자 선택 후보로 보존한다", () => {
    const error = new ApiRequestError(
      409,
      {
        detail: {
          code: "nearby_place_confirmation_required",
          nearby_places: [
            {
              place_id: 91,
              name: "월정리 해변",
              official_address: "제주 제주시 구좌읍",
              latitude: 33.556,
              longitude: 126.795,
              distance_m: 12.4,
              name_compatible: true,
              provider_id_match: null,
            },
          ],
        },
      },
      "conflict",
    );
    expect(parseNearbyPlaceConflict(error)).toEqual([
      expect.objectContaining({
        placeId: 91,
        name: "월정리 해변",
        distanceMeters: 12.4,
        nameCompatible: true,
      }),
    ]);
  });
});

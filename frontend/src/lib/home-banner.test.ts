import { describe, expect, it } from "vitest";

import { homeBannerModel } from "@/lib/home-banner";

describe("homeBannerModel", () => {
  it("둘 다 0이면 배너를 숨긴다", () => {
    const model = homeBannerModel(0, 0);
    expect(model.show).toBe(false);
    expect(model.showReview).toBe(false);
    expect(model.showAttention).toBe(false);
  });

  it("검수 대기만 있으면 검수 조각만 노출한다", () => {
    const model = homeBannerModel(12, 0);
    expect(model).toEqual({
      show: true,
      showReview: true,
      showAttention: false,
      reviewPending: 12,
      openAttention: 0,
    });
  });

  it("확인 필요 작업만 있으면 attention 조각만 노출한다", () => {
    const model = homeBannerModel(0, 3);
    expect(model.show).toBe(true);
    expect(model.showReview).toBe(false);
    expect(model.showAttention).toBe(true);
    expect(model.openAttention).toBe(3);
  });

  it("둘 다 있으면 둘 다 노출한다", () => {
    const model = homeBannerModel(5, 2);
    expect(model.show).toBe(true);
    expect(model.showReview).toBe(true);
    expect(model.showAttention).toBe(true);
  });

  it("음수·NaN은 0으로 방어한다", () => {
    expect(homeBannerModel(-4, Number.NaN).show).toBe(false);
  });
});

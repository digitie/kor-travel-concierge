// 홈(결과) 화면 상단 행동 배너 모델(T-192, U12). 검수 대기 N건과 확인 필요 작업 K건을
// 각각 노출하고, 둘 다 0이면 배너 자체를 숨긴다(내부 도구 기준 잡음 최소화).

export type HomeBannerModel = {
  show: boolean;
  showReview: boolean;
  showAttention: boolean;
  reviewPending: number;
  openAttention: number;
};

function normalizeCount(value: number): number {
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

export function homeBannerModel(
  reviewPending: number,
  openAttention: number,
): HomeBannerModel {
  const review = normalizeCount(reviewPending);
  const attention = normalizeCount(openAttention);
  const showReview = review > 0;
  const showAttention = attention > 0;
  return {
    show: showReview || showAttention,
    showReview,
    showAttention,
    reviewPending: review,
    openAttention: attention,
  };
}

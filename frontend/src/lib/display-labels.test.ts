import { describe, expect, it } from "vitest";

import {
  queueReasonBadgeVariant,
  queueReasonLabel,
  sourceKindLabel,
} from "./display-labels";
import type { ReviewQueueReason, ReviewSourceKind } from "./api";

describe("queueReasonLabel", () => {
  it.each<[ReviewQueueReason, string]>([
    ["ungrounded", "원문 근거 미확인"],
    ["name_mismatch", "장소명 불일치"],
    ["region_mismatch", "지역 불일치"],
    ["source_conflict", "출처 간 충돌"],
    ["source_low_confidence", "출처 대조 신뢰도 낮음"],
    ["source_uncertain", "출처 대조 불확실"],
    ["ambiguous", "후보 모호"],
    ["no_result", "검색 결과 없음"],
    ["vworld_unrefined_single", "VWorld 미정제 단일 결과"],
    ["foreign", "해외 후보"],
    ["description_only", "설명문 전용"],
    ["visual_only", "시각 근거 전용"],
    ["provider_missing", "provider 근거 누락"],
    ["extraction_only", "추출 직후"],
  ])("%s를 사용자 사유로 표시한다", (reason, label) => {
    expect(queueReasonLabel(reason)).toBe(label);
  });

  it.each<ReviewQueueReason>([
    "ungrounded",
    "name_mismatch",
    "region_mismatch",
    "source_conflict",
    "source_low_confidence",
    "source_uncertain",
  ])("%s를 높은 우선순위로 표시한다", (reason) => {
    expect(queueReasonBadgeVariant(reason)).toBe("destructive");
  });

  it("일반 사유는 보조 배지로 표시한다", () => {
    expect(queueReasonBadgeVariant("extraction_only")).toBe("secondary");
  });
});

describe("sourceKindLabel", () => {
  it.each<[ReviewSourceKind, string]>([
    ["transcript", "자막"],
    ["url_summary", "영상 URL 요약"],
    ["reconcile", "출처 대조"],
    ["manual", "사용자 입력"],
    ["geocoding", "지오코딩"],
    ["description", "영상 설명"],
    ["visual", "영상 프레임"],
  ])("%s를 사용자 출처로 표시한다", (source, label) => {
    expect(sourceKindLabel(source)).toBe(label);
  });
});

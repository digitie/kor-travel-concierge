import type { DestinationGroupDim, ReviewSourceFacets } from "@/lib/api";

/**
 * 검수 그룹 셀렉터 옵션. 세 provenance 차원(channel/playlist/keyword)을 후보
 * provenance facet의 통일형 `{value,label,candidate_count}`에서 뽑는다(T-187).
 */
export function groupOptions(
  dim: DestinationGroupDim,
  facets: ReviewSourceFacets | undefined,
): { value: string; label: string; count: number }[] {
  if (!facets) return [];
  const items =
    dim === "channel"
      ? facets.channels
      : dim === "playlist"
        ? facets.playlists
        : dim === "keyword"
          ? facets.keywords
          : [];
  return items.map((item) => ({
    value: item.value,
    label: item.label,
    count: item.candidate_count,
  }));
}

/**
 * 선택된 그룹값의 표시 라벨. facet lookup이 실패하면(현재 filter로 해당 출처가
 * facet에서 사라진 딥링크 groupValue, 아직 미로딩, 빈 라벨) **raw groupValue를
 * fallback**으로 써서 트리거가 공백이 되지 않게 한다(T-187).
 */
export function groupValueLabel(
  dim: DestinationGroupDim,
  value: string | null,
  facets: ReviewSourceFacets | undefined,
): string {
  if (!value) return "";
  const option = groupOptions(dim, facets).find((opt) => opt.value === value);
  if (option && option.label.trim()) {
    return `${option.label} (${option.count})`;
  }
  return value;
}

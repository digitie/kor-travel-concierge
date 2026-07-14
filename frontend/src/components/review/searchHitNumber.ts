import type { PlaceSearchHit } from "@/lib/api";
import { isPlaceHitStorageAllowed } from "@/lib/review-provenance";

/**
 * 선택 가능 hit(저장 허용 + 좌표 존재)만 렌더 순서대로 모은 단일 정본(T-187).
 * 키보드 1–9, 행 번호 배지, 지도 번호가 모두 이 배열의 같은 index를 쓴다 —
 * 세 표면이 항상 같은 순서/번호가 되도록 여기에서만 selectable을 판정한다.
 */
export function selectableSearchHits(
  allHits: readonly PlaceSearchHit[],
): PlaceSearchHit[] {
  return allHits.filter(
    (hit) =>
      isPlaceHitStorageAllowed(hit) &&
      hit.latitude != null &&
      hit.longitude != null,
  );
}

/**
 * 선택 가능 hit의 1–9 단축키/배지 서수(index+1). 선택 불가하거나 목록에 없거나
 * 9를 넘으면 배지·단축키를 붙이지 않도록 null을 반환한다. 이 번호는
 * `selectableSearchHits`의 index 기반이라 지도 placeId(index+1)와 정확히 일치한다.
 */
export function searchHitShortcutNumber(
  selectableHits: readonly PlaceSearchHit[] | undefined,
  hit: PlaceSearchHit,
  selectable: boolean,
): number | null {
  if (!selectable || !selectableHits) return null;
  const ordinal = selectableHits.indexOf(hit);
  return ordinal >= 0 && ordinal < 9 ? ordinal + 1 : null;
}

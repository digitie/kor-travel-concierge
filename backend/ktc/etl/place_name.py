"""장소 이름 정규화·동일성 판정 (자동확정 게이트·배치 dedup·병합 제안 공용, T-167).

`geocode_service`(자동확정 이름 게이트), `batch_poi_service`(같은 영상 내 중복 후보
dedup), `place_service`(병합 제안)가 **하나의** 정규화·비교 규칙을 공유하도록 단일
출처로 둔다(로드맵 PR-14 개정판, D6).

- `normalize_place_name`: 공백 제거 + casefold 후, **보수적** 지점 접미
  (`본점`·`본관`·`직영점`)만 끝에서 제거한다. 이들은 "THE 본점 == 상호"처럼 지점을 구분하지
  않는 일반 표기라 제거해도 안전하다. 반면 **`N호점`은 서로 다른 실지점을 구분하는 식별자**
  ("롯데리아 1호점" ≠ "롯데리아 2호점")라 제거하면 별개 지점을 뭉개 정밀도를 해치므로
  **제거하지 않는다**(T-166 정밀도 우선 방향과 정합, ADR-39). 광범위한 `…점$` 제거도 서로
  다른 지점("대전역점"↔"본점")을 뭉개므로 **하지 않는다**(로드맵 §10.4 금지 항목).
- `names_match`: 두 이름이 같은 장소를 가리키는지의 pairwise 판정(정규화 동일 또는
  구체적 부분 포함). 세 값 중 아무 한 쌍만 맞아도 통과하던 any-pair(C8)는 만들지 않는다.
"""

from __future__ import annotations

import re

# 부분 포함 판정의 최소 길이·비율(짧은 부분명 false-positive 재사용 방지, T-050 계승).
_MIN_CONTAINED_NAME_LENGTH = 4
_MIN_CONTAINED_NAME_RATIO = 0.6

# 보수적 지점 접미. 공백 제거된 정규화 문자열 끝에서만 제거한다. `\s*`는 비정규화 입력
# 호환용(정규화 후엔 공백이 없어 무해)이다. `N호점`은 실지점 식별자라 제외하고(정밀도),
# 광범위한 `…점$`은 절대 넣지 않는다(오병합, ADR-39).
_BRANCH_SUFFIX_RE = re.compile(r"\s*(본점|본관|직영점)$")


def normalize_place_name(value: str | None) -> str:
    """공백 제거 + casefold + 보수적 지점 접미 제거로 비교용 정규화 이름을 만든다.

    "성심당"·"성심당 본점"·"성심당본점"은 모두 "성심당"으로 정규화된다. "롯데리아 1호점"·
    "성심당 대전역점"의 `N호점`·`대전역점`은 실지점 식별자라 접미 목록에 없어 유지되며,
    "롯데리아 1호점"과 "롯데리아 2호점"은 서로 다른 정규화 이름으로 남는다(ADR-39).
    이름 전체가 접미뿐인 병리적 입력("본점")은 빈 문자열로 붕괴하지 않도록 원 정규화값을
    보존한다(서로 다른 장소가 빈 키로 오병합되는 것을 막는다).
    """
    collapsed = "".join((value or "").casefold().split())
    stripped = _BRANCH_SUFFIX_RE.sub("", collapsed)
    return stripped or collapsed


def names_match(left: str | None, right: str | None) -> bool:
    """두 이름이 동일 장소를 가리키는지의 pairwise 판정.

    정규화가 동일하거나, 한쪽이 다른 쪽을 충분히 구체적으로 포함하면 True. 한쪽이 비면
    검증 불가로 False.
    """
    a, b = normalize_place_name(left), normalize_place_name(right)
    if not a or not b:
        return False
    if a == b:
        return True
    return is_specific_contained_name(a, b)


def is_specific_contained_name(left: str, right: str) -> bool:
    """정규화된 두 이름 중 하나가 다른 하나를 충분히 길게·높은 비율로 포함하는지."""
    if left not in right and right not in left:
        return False
    shorter, longer = sorted((left, right), key=len)
    return (
        len(shorter) >= _MIN_CONTAINED_NAME_LENGTH
        and len(shorter) / len(longer) >= _MIN_CONTAINED_NAME_RATIO
    )

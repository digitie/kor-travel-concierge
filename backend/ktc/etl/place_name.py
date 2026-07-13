"""장소 이름 정규화·동일성 판정 (자동확정 게이트·배치 dedup·병합 제안 공용, T-167).

`geocode_service`(자동확정 이름 게이트), `batch_poi_service`(같은 영상 내 중복 후보
dedup), `place_service`(병합 제안)가 **하나의** 정규화·비교 규칙을 공유하도록 단일
출처로 둔다(로드맵 PR-14 개정판, D6).

- `normalize_place_name`: 공백 제거 + casefold 후, **보수적** 지점 접미
  (`본점`·`본관`·`직영점`·`N호점`)만 끝에서 제거한다. 이 목록은 오병합 위험이 낮은
  일반 지점 표기로 한정하며, 광범위한 `…점$` 제거는 서로 다른 지점("대전역점"↔
  "성심당본점")을 뭉개 오병합을 유발하므로 **하지 않는다**(로드맵 §10.4 금지 항목).
- `names_match`: 두 이름이 같은 장소를 가리키는지의 pairwise 판정(정규화 동일 또는
  구체적 부분 포함). 세 값 중 아무 한 쌍만 맞아도 통과하던 any-pair(C8)는 만들지 않는다.
"""

from __future__ import annotations

import re

# 부분 포함 판정의 최소 길이·비율(짧은 부분명 false-positive 재사용 방지, T-050 계승).
_MIN_CONTAINED_NAME_LENGTH = 4
_MIN_CONTAINED_NAME_RATIO = 0.6

# 보수적 지점 접미. 공백 제거된 정규화 문자열 끝에서만 제거한다. `\s*`는 비정규화 입력
# 호환용(정규화 후엔 공백이 없어 무해)이다. 광범위한 `…점$`은 절대 넣지 않는다(오병합).
_BRANCH_SUFFIX_RE = re.compile(r"\s*(본점|본관|직영점|[0-9]+호점)$")


def normalize_place_name(value: str | None) -> str:
    """공백 제거 + casefold + 보수적 지점 접미 제거로 비교용 정규화 이름을 만든다.

    "성심당"·"성심당 본점"·"성심당본점"은 모두 "성심당"으로, "롯데리아 1호점"은
    "롯데리아"로 정규화된다. "성심당 대전역점"의 "대전역점"은 접미 목록에 없어 유지된다.
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

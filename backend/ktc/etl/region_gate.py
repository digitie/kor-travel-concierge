"""행정구역(시도) 교차 검증 게이트 (D4, 로드맵 PR-12).

`location_hint`의 지역 토큰과 지오코딩 확정 주소의 시도 토큰을 대조해 시도 수준의
불일치("대구 동성로"인데 서울 좌표로 확정)를 자동확정 전에 잡아낸다. 역지오코딩 추가
호출 없이 provider 응답에 이미 포함된 주소 문자열만으로 판정한다(비용 0).

토큰 정규화 규칙을 여기 한 곳에 고정한다(구현자마다 다른 게이트가 나오지 않도록):
축약 별칭("대구"↔"대구광역시", "전북"↔"전라북도")은 아래 **명시적 alias asset**
(`SIDO_ALIASES`)으로 정규화한다. 문서가 재사용을 언급한 `admin_region_service`는
외부 reverse API 클라이언트일 뿐 시도 별칭 parser가 없으므로 여기서 신설한다(B3 검증).

게이트 정책:
- hint에서 시도를 못 뽑으면(지역 토큰 부재) 검증 신호가 없으므로 **통과**한다.
- 확정 주소에서 시도를 못 뽑아도(주소 파싱 실패) **통과**한다(신호 부재는 차단 사유 아님).
- 둘 다 시도가 있고 canonical 값이 다르면 **불일치**(needs_review + region_mismatch).

시군구 수준까지 강제하면 별칭·동음 지명으로 오검출(needs_review 폭증)이 잦아 정밀도가
떨어지므로, 이번 게이트는 시도 수준만 차단 신호로 쓴다(로드맵의 정밀도 우선 원칙).
"""

from __future__ import annotations

# canonical 시도 key -> 허용 surface 표기(명시적 alias asset). surface는 접미사
# 포함/축약 표기를 모두 담는다. 긴 표기가 짧은 표기보다 우선 매칭된다(아래 참조).
SIDO_ALIASES: dict[str, tuple[str, ...]] = {
    "서울": ("서울특별시", "서울시", "서울"),
    "부산": ("부산광역시", "부산시", "부산"),
    "대구": ("대구광역시", "대구시", "대구"),
    "인천": ("인천광역시", "인천시", "인천"),
    "광주": ("광주광역시", "광주시", "광주"),
    "대전": ("대전광역시", "대전시", "대전"),
    "울산": ("울산광역시", "울산시", "울산"),
    "세종": ("세종특별자치시", "세종시", "세종"),
    "경기": ("경기도", "경기"),
    "강원": ("강원특별자치도", "강원도", "강원"),
    "충북": ("충청북도", "충북"),
    "충남": ("충청남도", "충남"),
    "전북": ("전북특별자치도", "전라북도", "전북"),
    "전남": ("전라남도", "전남"),
    "경북": ("경상북도", "경북"),
    "경남": ("경상남도", "경남"),
    "제주": ("제주특별자치도", "제주도", "제주"),
}

# (surface, canonical)을 표기 길이 내림차순으로 고정한다. "대구광역시"가 "대구"보다
# 먼저 매칭되게 해 접미사 포함 표기를 우선한다(부분 매칭 오검출 축소).
_SURFACE_LOOKUP: tuple[tuple[str, str], ...] = tuple(
    sorted(
        (
            (surface, canonical)
            for canonical, surfaces in SIDO_ALIASES.items()
            for surface in surfaces
        ),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
)


def sido_of(text: str | None) -> str | None:
    """텍스트에서 시도 canonical key를 하나 찾아 반환한다(없으면 None).

    공백을 제거한 뒤 가장 긴 surface 표기를 우선 탐색하고, 같은 길이면 더 앞선
    위치를 택한다. 확정 주소는 보통 시도로 시작하므로 이 규칙이 주소·hint 모두에
    안정적으로 작동한다.
    """
    if not text:
        return None
    normalized = "".join(text.split())
    if not normalized:
        return None
    best_canonical: str | None = None
    best_index = len(normalized) + 1
    best_len = 0
    for surface, canonical in _SURFACE_LOOKUP:
        index = normalized.find(surface)
        if index == -1:
            continue
        # surface는 길이 내림차순이므로 더 긴 표기를 이미 봤으면(best_len 큼) 유지한다.
        if len(surface) < best_len:
            break
        if len(surface) > best_len or index < best_index:
            best_canonical = canonical
            best_index = index
            best_len = len(surface)
    return best_canonical


def region_conflict(location_hint: str | None, *address_texts: str | None) -> bool:
    """hint 시도와 확정 주소 시도가 모두 있고 서로 다르면 True(불일치).

    둘 중 하나라도 시도를 추출하지 못하면 검증 신호가 없으므로 False(통과)를 반환한다.
    """
    hint_sido = sido_of(location_hint)
    if hint_sido is None:
        return False
    result_sido: str | None = None
    for text in address_texts:
        result_sido = sido_of(text)
        if result_sido is not None:
            break
    if result_sido is None:
        return False
    return hint_sido != result_sido

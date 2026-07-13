"""행정구역(시도) 교차 검증 게이트 단위 테스트 (T-166, D4, 로드맵 PR-12).

DB 없이 시도 토큰 추출·별칭 정규화·불일치 판정을 검증한다.
"""

from __future__ import annotations

from ktc.etl import region_gate


# --- 시도 토큰 추출 ---


def test_sido_of_extracts_full_form():
    assert region_gate.sido_of("서울특별시 강남구 테헤란로") == "서울"
    assert region_gate.sido_of("부산광역시 해운대구") == "부산"
    assert region_gate.sido_of("제주특별자치도 서귀포시") == "제주"


def test_sido_of_extracts_abbreviation():
    assert region_gate.sido_of("대구 동성로") == "대구"
    assert region_gate.sido_of("전북 전주 한옥마을") == "전북"


def test_sido_of_maps_alias_to_same_canonical():
    # "대구"↔"대구광역시", "전북"↔"전라북도" 축약 별칭이 같은 canonical로 정규화된다.
    assert region_gate.sido_of("대구") == region_gate.sido_of("대구광역시")
    assert region_gate.sido_of("전북") == region_gate.sido_of("전라북도")


def test_sido_of_prefers_longer_prefix_form():
    # "경기도 광주시"는 경기(광주 metro 아님)로 잡아야 한다(긴 표기 우선).
    assert region_gate.sido_of("경기도 광주시 오포읍") == "경기"


def test_sido_of_returns_none_without_region_token():
    assert region_gate.sido_of("동성로 맛집") is None
    assert region_gate.sido_of(None) is None
    assert region_gate.sido_of("") is None


# --- 불일치 판정 ---


def test_region_conflict_true_on_sido_mismatch():
    # hint는 대구인데 확정 주소가 서울 → 불일치.
    assert region_gate.region_conflict("대구 동성로", "서울특별시 중구 세종대로") is True


def test_region_conflict_false_on_sido_match_with_alias():
    # hint "대구"와 결과 "대구광역시"는 별칭이므로 일치(통과).
    assert (
        region_gate.region_conflict("대구 동성로", "대구광역시 중구 동성로") is False
    )


def test_region_conflict_false_when_hint_has_no_region():
    # 검증 신호 부재 → 통과.
    assert region_gate.region_conflict("동성로 카페", "서울특별시 중구") is False


def test_region_conflict_false_when_result_has_no_sido():
    # 확정 주소에서 시도를 못 뽑으면 통과(신호 부재는 차단 사유 아님).
    assert region_gate.region_conflict("대구 동성로", "중구 동성로2가") is False


def test_region_conflict_scans_multiple_address_texts():
    # 첫 인자(도로명)가 시도 없이 와도 다음 인자(지번)에서 시도를 찾는다.
    assert (
        region_gate.region_conflict("대구 동성로", None, "서울특별시 중구 을지로")
        is True
    )

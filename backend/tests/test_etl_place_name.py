"""장소 이름 정규화·병합용 동일성 판정 테스트 (T-167, 로드맵 PR-14 개정판, D6)."""

from __future__ import annotations

from ktc.etl.place_name import names_match, normalize_place_name


def test_normalize_strips_conservative_branch_suffixes():
    # 본점/본관/직영점/N호점만 제거하고, 공백·대소문자 변형은 무시한다.
    assert normalize_place_name("성심당 본점") == "성심당"
    assert normalize_place_name("성심당본점") == "성심당"
    assert normalize_place_name("성심당") == "성심당"
    assert normalize_place_name("스타벅스 강남 본관") == "스타벅스강남"
    assert normalize_place_name("교촌치킨 직영점") == "교촌치킨"
    assert normalize_place_name("롯데리아 1호점") == "롯데리아"
    assert normalize_place_name("맘스터치 12호점") == "맘스터치"


def test_normalize_keeps_non_generic_branch_names():
    # 광범위한 `…점$` 제거는 금지(오병합 방지) — 구체적 지점명은 유지한다.
    assert normalize_place_name("성심당 대전역점") == "성심당대전역점"
    assert normalize_place_name("올리브영 강남점") == "올리브영강남점"
    assert normalize_place_name("면세점") == "면세점"


def test_normalize_all_suffix_does_not_collapse_to_empty():
    # 이름 전체가 접미뿐이면 빈 문자열로 붕괴하지 않는다(서로 다른 장소의 빈 키 오병합 방지).
    assert normalize_place_name("본점") == "본점"
    assert normalize_place_name("1호점") == "1호점"


def test_normalize_casefold_and_whitespace():
    assert normalize_place_name("Cafe  Onul") == "cafeonul"
    assert normalize_place_name(None) == ""
    assert normalize_place_name("") == ""


def test_names_match_dedups_branch_variants():
    assert names_match("성심당", "성심당 본점")
    assert names_match("성심당 본점", "성심당본점")
    # 서로 다른 지점(구체적 지점명)은 병합하지 않는다.
    assert not names_match("성심당 본점", "성심당 대전역점")


def test_names_match_pairwise_and_short_partial_rules():
    assert names_match("월정리 카페", "월정리카페")
    assert not names_match("카페", "월정리카페")  # 짧은 부분명 false-positive 방지
    assert not names_match("", "성심당")
    assert not names_match("성심당", None)

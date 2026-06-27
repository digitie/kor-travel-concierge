"""category_catalog 로더와 category_suggestion 선택기 단위 테스트 (T-070).

DB 없이 순수 함수만 검증한다. 실제 Gemini 호출은 주입형 fake llm으로 대체한다.
"""

from __future__ import annotations

import json

from ktc.etl import category_catalog, category_suggestion


# --- 카탈로그 로더 ---


def test_catalog_loads_full_table():
    cats = category_catalog.iter_categories()
    assert len(cats) == 144
    assert category_catalog.synced_on() == "2026-05-25"


def test_catalog_is_known_code():
    assert category_catalog.is_known_code("0") is True
    assert category_catalog.is_known_code("01050100") is True
    assert category_catalog.is_known_code("00000000") is True
    assert category_catalog.is_known_code("99999999") is False
    assert category_catalog.is_known_code(None) is False


def test_catalog_label_for():
    assert category_catalog.label_for("0") == "unknown"
    assert category_catalog.label_for("01000000") == "관광"
    assert "해수욕장" in (category_catalog.label_for("01050100") or "")
    assert category_catalog.label_for("99999999") is None


def test_prompt_catalog_excludes_root_and_lists_codes():
    text = category_catalog.prompt_catalog()
    assert "01050100" in text
    # 분류 미지정 루트는 선택 목록에서 제외한다.
    assert not any(line.startswith("00000000") for line in text.splitlines())


# --- 선택 결과 파싱/검증 ---


def test_select_valid_code():
    assert category_suggestion.select_category_code('{"category_code": "01050100"}') == "01050100"


def test_select_rejects_unclassified():
    assert category_suggestion.select_category_code('{"category_code": "00000000"}') is None


def test_select_rejects_unknown_code():
    assert category_suggestion.select_category_code('{"category_code": "99999999"}') is None


def test_select_rejects_invalid_json():
    assert category_suggestion.select_category_code("not json") is None


def test_select_rejects_non_dict():
    assert category_suggestion.select_category_code('["01050100"]') is None


# --- suggest_category_code (주입형 llm) ---


def test_suggest_returns_code_from_fake_llm():
    captured = {}

    def fake_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps({"category_code": "01050100", "reason": "해변"})

    code = category_suggestion.suggest_category_code(
        name="월정리 해변", category_label="해변", llm=fake_llm
    )
    assert code == "01050100"
    # 프롬프트에 카탈로그와 장소명이 포함된다.
    assert "카테고리 목록" in captured["prompt"]
    assert "월정리 해변" in captured["prompt"]


def test_suggest_none_llm_returns_none():
    assert category_suggestion.suggest_category_code(name="월정리 해변", llm=None) is None


def test_suggest_empty_name_returns_none():
    assert category_suggestion.suggest_category_code(name="", llm=lambda p: "{}") is None


def test_suggest_swallows_llm_error():
    def boom(prompt: str) -> str:
        raise RuntimeError("gemini down")

    assert category_suggestion.suggest_category_code(name="월정리 해변", llm=boom) is None


def test_suggest_rejects_hallucinated_code():
    def fake_llm(prompt: str) -> str:
        return json.dumps({"category_code": "12345678"})

    assert category_suggestion.suggest_category_code(name="월정리 해변", llm=fake_llm) is None

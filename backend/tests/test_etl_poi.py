"""poi_extraction JSON Schema 파싱·재시도 테스트."""

from __future__ import annotations

import json

import pytest

from app.etl import poi_extraction
from app.etl.poi_extraction import POIExtractionError, extract_pois

_VALID_JSON = json.dumps(
    {
        "summary": "제주 맛집 영상",
        "description_gemini_corrected": "오탈자를 고친 설명",
        "places": [
            {
                "name": "월정리 카페",
                "speaker_note": "뷰가 좋다고 소개",
                "gemini_enriched_description": "월정리 해변 인근 카페",
                "location_hint": "제주 구좌읍 월정리",
                "timestamp_start": "00:30",
                "timestamp_end": "01:10",
                "category": "카페",
            }
        ],
    },
    ensure_ascii=False,
)


def test_extract_valid():
    result = extract_pois(
        timestamped_transcript="[00:30] 월정리 카페", description_raw="원문", llm=lambda _: _VALID_JSON
    )
    assert result.summary == "제주 맛집 영상"
    assert result.description_gemini_corrected == "오탈자를 고친 설명"
    assert len(result.places) == 1
    assert result.places[0].name == "월정리 카페"
    assert result.places[0].category == "카페"


def test_retry_then_success():
    calls = {"n": 0}

    def flaky_llm(_prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return "이건 JSON이 아님"  # 1차 파싱 실패
        return _VALID_JSON

    result = extract_pois(
        timestamped_transcript="t", description_raw=None, llm=flaky_llm, max_retries=2
    )
    assert calls["n"] == 2
    assert len(result.places) == 1


def test_all_retries_fail_raises():
    with pytest.raises(POIExtractionError):
        extract_pois(
            timestamped_transcript="t", description_raw=None, llm=lambda _: "not json", max_retries=1
        )


def test_schema_validation_rejects_missing_name():
    bad = json.dumps({"summary": "s", "places": [{"speaker_note": "이름 없음"}]})
    with pytest.raises(POIExtractionError):
        extract_pois(timestamped_transcript="t", description_raw=None, llm=lambda _: bad, max_retries=0)


def test_response_schema_shape():
    schema = poi_extraction.RESPONSE_JSON_SCHEMA
    assert schema["type"] == "object"
    assert "places" in schema["properties"]
    assert schema["properties"]["places"]["items"]["required"] == ["name"]

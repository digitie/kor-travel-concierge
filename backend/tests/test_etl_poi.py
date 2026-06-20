"""poi_extraction JSON Schema 파싱·재시도 테스트."""

from __future__ import annotations

import json

import pytest

from ktc.etl import gemini_client, poi_extraction
from ktc.etl.poi_extraction import POIExtractionError, build_prompt, extract_pois

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


def test_make_gemini_llm_sends_schema_and_extracts_text(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": _VALID_JSON},
                            ]
                        }
                    }
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(gemini_client.requests, "post", fake_post)

    llm = poi_extraction.make_gemini_llm(
        api_key="gemini-key",
        model="gemini-flash-latest",
        timeout_seconds=3,
    )

    assert llm("프롬프트") == _VALID_JSON
    assert captured["url"].endswith("/models/gemini-flash-latest:generateContent")
    assert captured["headers"]["X-goog-api-key"] == "gemini-key"
    assert captured["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["json"]["generationConfig"]["responseSchema"] is poi_extraction.RESPONSE_JSON_SCHEMA


def test_build_prompt_embeds_description_and_extraction_instruction():
    description = "협재 해수욕장과 한담 해안산책로를 영상 설명에 적어 둠"
    prompt = build_prompt(
        timestamped_transcript="[00:10] 협재 해수욕장 도착",
        description_raw=description,
    )
    # 영상 설명 원문이 프롬프트에 그대로 포함되어야 한다.
    assert "[영상 설명 원문]" in prompt
    assert description in prompt
    # 자막뿐 아니라 영상 설명에서도 장소를 추출하라는 지시가 있어야 한다.
    assert "영상 설명 원문 양쪽에 등장하는 장소(POI)를 모두 추출" in prompt
    assert "영상 설명에만 적혀 있고 자막에는 없는 장소도" in prompt
    # 기존 보정 지시는 유지된다(ADR-16 원문/보정 분리).
    assert "영상 설명의 오탈자·문맥을 보정" in prompt


def test_build_prompt_handles_missing_description():
    prompt = build_prompt(timestamped_transcript="t", description_raw=None)
    assert "[영상 설명 원문]\n\n" in prompt


def test_extract_pois_passes_description_into_llm_prompt():
    captured: dict[str, str] = {}
    description = "성산일출봉 근처 카페 정보는 영상 설명에만 있음"

    def capturing_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return _VALID_JSON

    extract_pois(
        timestamped_transcript="[00:05] 안녕하세요",
        description_raw=description,
        llm=capturing_llm,
    )
    # LLM에 전달된 프롬프트에 영상 설명 원문이 포함되어야 한다.
    assert description in captured["prompt"]
    assert "[영상 설명 원문]" in captured["prompt"]

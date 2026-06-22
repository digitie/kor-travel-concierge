"""자막 교정 프롬프트 + dispatch body 테스트(Gemini 호출 없이)."""

from __future__ import annotations

from ktc.etl import llm_client, transcript_correction


def test_build_correction_prompt_includes_description_and_transcript():
    prompt = transcript_correction.build_correction_prompt(
        transcript="[00:01] 협재 해수욕장 도착", description="협재 해수욕장·한담 해안산책로"
    )
    assert "[영상 설명]" in prompt
    assert "협재 해수욕장·한담 해안산책로" in prompt
    assert "[교정할 자막]" in prompt
    assert "[00:01] 협재 해수욕장 도착" in prompt


def test_build_correction_prompt_handles_missing_description():
    prompt = transcript_correction.build_correction_prompt(
        transcript="t", description=None
    )
    assert "(없음)" in prompt


def test_build_gemini_body_supports_system_instruction_and_temperature():
    body = llm_client.build_gemini_body(
        "프롬프트",
        None,
        system_instruction="너는 교정자다",
        temperature=0.1,
    )
    assert body["systemInstruction"]["parts"][0]["text"] == "너는 교정자다"
    assert body["generationConfig"]["temperature"] == 0.1
    # responseSchema 없음(평문 교정)
    assert "responseSchema" not in body["generationConfig"]


def test_build_gemini_body_response_schema_plus_temperature():
    body = llm_client.build_gemini_body(
        "p", {"type": "object"}, temperature=0.1
    )
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseSchema"] == {"type": "object"}
    assert body["generationConfig"]["temperature"] == 0.1

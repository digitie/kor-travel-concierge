"""batch_poi 프롬프트·파싱·검증 테스트(Gemini 호출 없이)."""

from __future__ import annotations

import json

from ktc.etl import batch_poi


def test_build_batch_prompt_wraps_each_video():
    prompt = batch_poi.build_batch_prompt(
        [("video_001", "자막 A"), ("video_002", "자막 B")]
    )
    assert prompt.startswith("<video_transcripts>")
    assert '<script video_id="video_001">' in prompt
    assert '<script video_id="video_002">' in prompt
    assert "자막 A" in prompt and "자막 B" in prompt


def test_batch_system_instruction_embeds_catalog_and_rules():
    sys = batch_poi.batch_system_instruction()
    assert "[카테고리 마스터 테이블]" in sys
    assert "교차 참조" in sys  # 교차참조 금지 지시
    assert "01050100" in sys  # 카탈로그 코드 포함


def test_parse_batch_drops_unknown_alias_and_validates_code():
    payload = json.dumps(
        {
            "results": [
                {
                    "video_id": "video_001",
                    "official_name": "감천문화마을",
                    "category_code": "01050100",
                },
                # 입력에 없는 alias → 폐기(교차오염/환각 차단)
                {
                    "video_id": "video_999",
                    "official_name": "다른영상 환각",
                    "category_code": "01050100",
                },
                # 미지 코드 → None
                {
                    "video_id": "video_001",
                    "official_name": "코드불량",
                    "category_code": "99999999",
                },
                # 이름 없음 → 폐기
                {"video_id": "video_001", "official_name": ""},
            ]
        },
        ensure_ascii=False,
    )
    pois = batch_poi.parse_batch(payload, valid_aliases={"video_001", "video_002"})
    names = [p.official_name for p in pois]
    assert "감천문화마을" in names
    assert "코드불량" in names
    assert "다른영상 환각" not in names
    assert "" not in names
    by_name = {p.official_name: p for p in pois}
    assert by_name["감천문화마을"].category_code == "01050100"
    assert by_name["코드불량"].category_code is None

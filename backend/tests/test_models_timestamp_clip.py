"""POI 타임스탬프 컬럼 방어적 클립 회귀 테스트.

`extracted_place_candidates`/`video_place_mappings`의 `timestamp_start/end`는
VARCHAR(64)로 넓혔고(20260620_0007), 모델 `@validates`가 64자 초과 값을 클립한다.
과거 VARCHAR(16) 제한이 16자 초과 Gemini 타임스탬프에서 적재 실패를 냈다(라이브 E2E 발견).
DB 없이 동작한다(assignment 시점 검증).
"""

from __future__ import annotations

from ktc.models.extracted_place_candidate import ExtractedPlaceCandidate
from ktc.models.video_place_mapping import VideoPlaceMapping


def test_candidate_long_timestamp_clipped_to_64():
    c = ExtractedPlaceCandidate(video_id="v1", timestamp_start="0" * 70, timestamp_end="9" * 100)
    assert len(c.timestamp_start) == 64
    assert len(c.timestamp_end) == 64


def test_mapping_long_timestamp_clipped_to_64():
    m = VideoPlaceMapping(video_id="v1", timestamp_start="a" * 65, timestamp_end="b" * 200)
    assert len(m.timestamp_start) == 64
    assert len(m.timestamp_end) == 64


def test_normal_timestamp_unchanged():
    # 16자 초과지만 64자 이하인 정상 포맷은 그대로 보존(과거 16자 제한 회귀 방지).
    ts = "00:22:00 - 00:35:00"
    c = ExtractedPlaceCandidate(video_id="v1", timestamp_start=ts)
    assert c.timestamp_start == ts
    assert len(ts) > 16


def test_none_timestamp_preserved():
    c = ExtractedPlaceCandidate(video_id="v1", timestamp_start=None)
    assert c.timestamp_start is None

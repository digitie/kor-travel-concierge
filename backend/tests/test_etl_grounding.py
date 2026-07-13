"""raw 자막 대조 grounding 판정·게이트 헬퍼 단위 테스트 (T-165, 로드맵 B3·G4).

DB 없이 grounding 로직과 gate 헬퍼(자동확정·export)를 검증한다. quote는 **원본 자막**과
대조한다(교정본이 아님).
"""

from __future__ import annotations

import json

from ktc.etl import batch_poi, grounding
from ktc.etl.geocode_service import _grounding_blocks_autoconfirm
from ktc.models import (
    EvidenceSourceKind,
    ExtractedPlaceCandidate,
    GroundingStatus,
    MatchStatus,
)
from ktc.services.feature_export_service import _export_grounding_blocked


# --- grounding 판정 ---

RAW = (
    "[00:03] 오늘은 부산역 국밥집에 왔습니다\n"
    "[00:07] 국물이 정말 진하고 맛있네요\n"
    "[00:12] 다음은 감천문화마을로 이동합니다"
)


def test_exact_quote_is_verified_raw():
    result = grounding.evaluate_transcript_grounding(
        "부산역 국밥집에 왔습니다", RAW
    )
    assert result.status is grounding.GroundingStatus.VERIFIED_RAW
    assert result.evidence_quote == "부산역 국밥집에 왔습니다"
    assert result.matched_segment_index == 0
    assert result.matched_segment_start_seconds == 3.0


def test_quote_spanning_segment_boundary_is_verified_raw():
    # 세그먼트 경계를 넘는 인용도 원문에 실존하면 verified(공백 정규화 후 부분 문자열).
    result = grounding.evaluate_transcript_grounding(
        "국물이 정말 진하고 맛있네요 다음은 감천문화마을로", RAW
    )
    assert result.status is grounding.GroundingStatus.VERIFIED_RAW


def test_modified_quote_is_unverified():
    # 변형 인용(원문에 없는 표현으로 바꿈) → unverified.
    result = grounding.evaluate_transcript_grounding(
        "부산역 최고의 국밥집에 방문했습니다", RAW
    )
    assert result.status is grounding.GroundingStatus.UNVERIFIED


def test_fabricated_quote_is_unverified():
    # 창작 인용(원문 어디에도 없음) → unverified.
    result = grounding.evaluate_transcript_grounding(
        "이곳은 서울에서 가장 유명한 카페입니다", RAW
    )
    assert result.status is grounding.GroundingStatus.UNVERIFIED


def test_missing_quote_is_missing():
    assert (
        grounding.evaluate_transcript_grounding(None, RAW).status
        is grounding.GroundingStatus.MISSING
    )
    assert (
        grounding.evaluate_transcript_grounding("", RAW).status
        is grounding.GroundingStatus.MISSING
    )
    # 너무 짧은 인용(근거로 쓸 수 없음)도 missing.
    assert (
        grounding.evaluate_transcript_grounding("국밥", RAW).status
        is grounding.GroundingStatus.MISSING
    )


def test_no_raw_text_fails_closed_as_unverified():
    # 대조할 raw 자막이 없으면 근거 확인 불가 → fail-closed(unverified, 자동확정 차단).
    result = grounding.evaluate_transcript_grounding("부산역 국밥집에 왔습니다", None)
    assert result.status is grounding.GroundingStatus.UNVERIFIED


def test_whitespace_normalization_matches_across_newlines_and_spaces():
    raw = "[00:01] 성심당    본점에서\n[00:04] 빵을 샀어요"
    result = grounding.evaluate_transcript_grounding("성심당 본점에서 빵을 샀어요", raw)
    assert result.status is grounding.GroundingStatus.VERIFIED_RAW


def test_raw_without_timestamp_markers_is_parsed():
    raw = "부산역 국밥집에 왔습니다\n국물이 진하네요"
    result = grounding.evaluate_transcript_grounding("부산역 국밥집에 왔습니다", raw)
    assert result.status is grounding.GroundingStatus.VERIFIED_RAW


# --- batch_poi 스키마 하위 호환 ---


def test_parse_batch_carries_evidence_quote_and_confidence():
    payload = json.dumps(
        {
            "results": [
                {
                    "video_id": "video_001",
                    "official_name": "감천문화마을",
                    "evidence_quote": "감천문화마을로 이동합니다",
                    "confidence": 0.82,
                }
            ]
        },
        ensure_ascii=False,
    )
    pois = batch_poi.parse_batch(payload, valid_aliases={"video_001"})
    assert len(pois) == 1
    assert pois[0].evidence_quote == "감천문화마을로 이동합니다"
    assert pois[0].confidence == 0.82


def test_parse_batch_backward_compatible_without_quote():
    # quote 없는 구 응답 재처리 시 크래시 없이 None으로 흡수(스키마 하위 호환).
    payload = json.dumps(
        {"results": [{"video_id": "video_001", "official_name": "감천문화마을"}]},
        ensure_ascii=False,
    )
    pois = batch_poi.parse_batch(payload, valid_aliases={"video_001"})
    assert len(pois) == 1
    assert pois[0].evidence_quote is None
    assert pois[0].confidence is None


# --- gate 헬퍼(자동확정·export) — in-memory 후보 ---


def _candidate(*, source_kind, grounding_status, match_status=MatchStatus.MATCHED):
    return ExtractedPlaceCandidate(
        video_id="v1",
        source_text="s",
        ai_place_name="장소",
        source_kind=source_kind,
        grounding_status=grounding_status,
        match_status=match_status,
    )


def test_autoconfirm_gate_blocks_ungrounded_transcript():
    for status in (
        GroundingStatus.UNVERIFIED,
        GroundingStatus.MISSING,
        GroundingStatus.LEGACY_UNKNOWN,
    ):
        cand = _candidate(
            source_kind=EvidenceSourceKind.TRANSCRIPT.value,
            grounding_status=status.value,
        )
        assert _grounding_blocks_autoconfirm(cand) is True


def test_autoconfirm_gate_allows_verified_transcript():
    cand = _candidate(
        source_kind=EvidenceSourceKind.TRANSCRIPT.value,
        grounding_status=GroundingStatus.VERIFIED_RAW.value,
    )
    assert _grounding_blocks_autoconfirm(cand) is False


def test_autoconfirm_gate_only_applies_to_transcript():
    # 비-transcript(예: url_summary)는 raw segment grounding 규칙 대상이 아니다.
    cand = _candidate(
        source_kind=EvidenceSourceKind.URL_SUMMARY.value,
        grounding_status=GroundingStatus.MISSING.value,
    )
    assert _grounding_blocks_autoconfirm(cand) is False


def test_export_gate_blocks_auto_matched_ungrounded_transcript():
    cand = _candidate(
        source_kind=EvidenceSourceKind.TRANSCRIPT.value,
        grounding_status=GroundingStatus.UNVERIFIED.value,
        match_status=MatchStatus.MATCHED,
    )
    assert _export_grounding_blocked(cand) is True


def test_export_gate_allows_human_confirmed_ungrounded():
    # 사람이 확정한(user_corrected) 후보는 grounding과 무관하게 export 허용.
    cand = _candidate(
        source_kind=EvidenceSourceKind.TRANSCRIPT.value,
        grounding_status=GroundingStatus.LEGACY_UNKNOWN.value,
        match_status=MatchStatus.USER_CORRECTED,
    )
    assert _export_grounding_blocked(cand) is False


def test_export_gate_allows_verified_transcript():
    cand = _candidate(
        source_kind=EvidenceSourceKind.TRANSCRIPT.value,
        grounding_status=GroundingStatus.VERIFIED_RAW.value,
        match_status=MatchStatus.MATCHED,
    )
    assert _export_grounding_blocked(cand) is False

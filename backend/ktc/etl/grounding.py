"""raw 자막 대조 grounding 검증 (T-165, 로드맵 PR-13 개정판, B3·G4).

POI 후보의 `evidence_quote`가 **raw timestamp segment**에 실존하는지 부분 문자열로
대조해 `GroundingStatus`로 분류한다. 대조 원천은 교정본(`transcript_corrected`)이 아니라
`TranscriptResult.to_timestamped_text()`가 저장한 **원본 자막**이다 — 교정본도 생성 모델
산출물이라 원문 증거가 될 수 없기 때문이다(로드맵 B3).

공백·타임스탬프 마커를 정규화한 뒤 대조하며, 대·소문자나 철자 교정은 하지 않는다
(원문 그대로 인용만 verified로 인정하는 raw grounding). LLM 자가 보고 confidence는 이
판정에 **절대** 쓰지 않는다(§2.4 가짜 정밀도 방지).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ktc.models import GroundingStatus

# 유효 인용으로 인정하는 정규화 후 최소 길이. 이보다 짧으면 근거로 쓸 수 없어 MISSING으로
# 둔다(2~3자짜리 자명한 부분일치가 verified_raw로 새는 것을 막는다).
_MIN_QUOTE_CHARS = 10

# `to_timestamped_text()`가 붙인 `[mm:ss]`/`[hh:mm:ss]` 마커(자막 본문이 아니라 직렬화
# 산출물). 분(minute)은 긴 영상에서 3자리 이상이 될 수 있어 `\d+`로 둔다.
_TIMESTAMP_MARKER = re.compile(r"\[\d+:\d{2}(?::\d{2})?\]")
_SEGMENT_LINE = re.compile(r"^\[(\d+):(\d{2})(?::(\d{2}))?\]\s?(.*)$")
_WS = re.compile(r"\s+")


def normalize_for_grounding(text: str | None) -> str:
    """타임스탬프 마커 제거 + 공백 정규화(대소문자·철자는 보존)."""
    if not text:
        return ""
    without_markers = _TIMESTAMP_MARKER.sub(" ", text)
    return _WS.sub(" ", without_markers).strip()


def parse_timestamped_segments(raw_text: str | None) -> list[tuple[float | None, str]]:
    """`[mm:ss] 텍스트` 직렬화(원본 자막 저장 형식)를 (start_seconds, text)로 되푼다.

    마커가 없는 줄은 start=None인 세그먼트로 둔다(마커 없이 저장된 원문도 흡수).
    """
    segments: list[tuple[float | None, str]] = []
    for line in (raw_text or "").splitlines():
        match = _SEGMENT_LINE.match(line)
        if match:
            g1, g2, g3, body = match.groups()
            if g3 is not None:
                start: float | None = int(g1) * 3600 + int(g2) * 60 + int(g3)
            else:
                start = int(g1) * 60 + int(g2)
            segments.append((float(start), body))
        elif line.strip():
            segments.append((None, line.strip()))
    return segments


@dataclass(frozen=True)
class GroundingResult:
    """grounding 판정 결과 + 매칭 세그먼트 ref(evidence JSON용)."""

    status: GroundingStatus
    evidence_quote: str | None
    matched_segment_index: int | None = None
    matched_segment_start_seconds: float | None = None


def _locate_segment(
    quote_norm: str, segments: list[tuple[float | None, str]]
) -> tuple[int | None, float | None]:
    """인용이 시작되는 세그먼트를 best-effort로 찾는다(gate에 쓰이지 않는 참조값)."""
    prefix = quote_norm[: min(len(quote_norm), 16)]
    for index, (start, text) in enumerate(segments):
        if prefix and prefix in normalize_for_grounding(text):
            return index, start
    head = quote_norm.split(" ", 1)[0]
    if head:
        for index, (start, text) in enumerate(segments):
            if head in normalize_for_grounding(text):
                return index, start
    return None, None


def evaluate_transcript_grounding(
    evidence_quote: str | None, raw_text: str | None
) -> GroundingResult:
    """`evidence_quote`를 raw 자막(`raw_text`)에 부분 문자열로 대조해 상태를 판정한다.

    - MISSING: 인용 미제공(또는 근거로 쓸 수 없을 만큼 짧음).
    - VERIFIED_RAW: 인용이 raw segment 텍스트에 실존(공백/마커 정규화 후).
    - UNVERIFIED: 인용은 있으나 raw에 없음(변형·창작 인용) 또는 대조할 raw가 없음.
    """
    quote_norm = normalize_for_grounding(evidence_quote)
    if len(quote_norm) < _MIN_QUOTE_CHARS:
        return GroundingResult(GroundingStatus.MISSING, (evidence_quote or None))

    segments = parse_timestamped_segments(raw_text)
    haystack = normalize_for_grounding(" ".join(text for _, text in segments))
    if not haystack:
        # 대조할 raw 자막이 없으면 근거를 확인할 수 없다 → fail-closed(자동확정 차단).
        return GroundingResult(GroundingStatus.UNVERIFIED, evidence_quote)
    if quote_norm in haystack:
        index, start = _locate_segment(quote_norm, segments)
        return GroundingResult(
            GroundingStatus.VERIFIED_RAW, evidence_quote, index, start
        )
    return GroundingResult(GroundingStatus.UNVERIFIED, evidence_quote)

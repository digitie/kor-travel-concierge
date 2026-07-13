"""raw 자막 대조 grounding 검증 (T-165, 로드맵 PR-13 개정판, B3·G4).

POI 후보의 `evidence_quote`가 **raw timestamp segment**에 실존하는지 부분 문자열로
대조해 `GroundingStatus`로 분류한다. 대조 원천은 교정본(`transcript_corrected`)이 아니라
`TranscriptResult.to_timestamped_text()`가 저장한 **원본 자막**이다 — 교정본도 생성 모델
산출물이라 원문 증거가 될 수 없기 때문이다(로드맵 B3).

**raw vs 교정본 잔여 오차단(코디네이터 MAJOR 1)**: POI 추출 LLM은 교정본만 입력받으므로
`evidence_quote`는 교정본 어휘로 나온다. 교정의 가장 흔한 분기는 장소명 주변 띄어쓰기
교정(raw `부산역 국밥집` → 교정 `부산역국밥집`)이라, CJK 문자 인접 공백을 제거하는 정규화로
이 분기를 흡수한다. 철자·고유명사 교정 분기는 여전히 unverified로 남지만(=needs_review로
안전) 이는 fail-closed다. **근본 해결(추출 LLM에 raw를 인용 원천으로 제공)은 이번 범위 밖**
이며, raw-vs-corrected 잔여 오차단율은 T-169 baseline live yield로 실측 후 재검토한다.

대·소문자나 철자 교정은 하지 않는다(원문 그대로 인용만 verified로 인정하는 raw grounding).
LLM 자가 보고 confidence는 이 판정에 **절대** 쓰지 않는다(§2.4 가짜 정밀도 방지).
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

# CJK(한글·한자·가나) 문자 범위. 교정본의 장소명 띄어쓰기 교정을 흡수하기 위해 CJK 문자에
# 인접한 공백만 제거한다(영문 단어 경계는 보존 — `New Balance`의 공백은 그대로).
_CJK = "ᄀ-ᇿ぀-ヿ㄰-㆏㐀-䶿一-鿿가-힣"
_CJK_ADJACENT_SPACE = re.compile(rf"(?<=[{_CJK}])\s+|\s+(?=[{_CJK}])")


def normalize_for_grounding(text: str | None) -> str:
    """타임스탬프 마커 제거 + 공백 정규화 + CJK 인접 공백 제거(대소문자·철자는 보존)."""
    if not text:
        return ""
    without_markers = _TIMESTAMP_MARKER.sub(" ", text)
    collapsed = _WS.sub(" ", without_markers).strip()
    return _CJK_ADJACENT_SPACE.sub("", collapsed)


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
class GroundingIndex:
    """video_id 1개의 grounding 대조 인덱스(정규화 haystack을 재사용해 재계산을 피한다).

    같은 영상의 POI가 여러 개면 evaluate마다 350k자 재정규화가 반복되므로(리뷰 MINOR-1),
    영상당 1회 만들어 재사용한다.
    """

    segments: list[tuple[float | None, str]]
    haystack: str


def build_grounding_index(raw_text: str | None) -> GroundingIndex:
    """원본 자막에서 정규화 haystack(+세그먼트)을 1회 계산한다(영상당 캐시용)."""
    segments = parse_timestamped_segments(raw_text)
    haystack = normalize_for_grounding(" ".join(text for _, text in segments))
    return GroundingIndex(segments=segments, haystack=haystack)


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
    evidence_quote: str | None,
    raw_text: str | None = None,
    *,
    index: GroundingIndex | None = None,
) -> GroundingResult:
    """`evidence_quote`를 raw 자막에 부분 문자열로 대조해 상태를 판정한다.

    `index`가 주어지면 재사용하고(영상당 1회 계산), 없으면 `raw_text`로 즉석 계산한다.

    - MISSING: 인용 미제공(또는 근거로 쓸 수 없을 만큼 짧음).
    - VERIFIED_RAW: 인용이 raw segment 텍스트에 실존(공백/마커/CJK 인접 공백 정규화 후).
    - UNVERIFIED: 인용은 있으나 raw에 없음(변형·창작 인용) 또는 대조할 raw가 없음.
    """
    quote_norm = normalize_for_grounding(evidence_quote)
    if len(quote_norm) < _MIN_QUOTE_CHARS:
        return GroundingResult(GroundingStatus.MISSING, (evidence_quote or None))

    grounding_index = index if index is not None else build_grounding_index(raw_text)
    if not grounding_index.haystack:
        # 대조할 raw 자막이 없으면 근거를 확인할 수 없다 → fail-closed(자동확정 차단).
        return GroundingResult(GroundingStatus.UNVERIFIED, evidence_quote)
    if quote_norm in grounding_index.haystack:
        seg_index, start = _locate_segment(quote_norm, grounding_index.segments)
        return GroundingResult(
            GroundingStatus.VERIFIED_RAW, evidence_quote, seg_index, start
        )
    return GroundingResult(GroundingStatus.UNVERIFIED, evidence_quote)

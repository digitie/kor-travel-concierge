"""YouTube 장소 후보 feature export와 evidence 공통 값."""

from __future__ import annotations

from enum import Enum


class EvidenceSourceKind(str, Enum):
    TRANSCRIPT = "transcript"
    URL_SUMMARY = "url_summary"
    RECONCILE = "reconcile"
    MANUAL = "manual"
    GEOCODING = "geocoding"
    DESCRIPTION = "description"
    VISUAL = "visual"


class FeatureExportStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    EXPORTED = "exported"
    REJECTED = "rejected"


class GroundingStatus(str, Enum):
    """후보 근거(evidence)가 원문 소스에 실존하는지의 기계 검증 상태(T-165, 로드맵 B3·G4).

    표시용 배지가 아니라 상태 전이(자동확정·export)를 막는 게이트 값이다. source별로
    검증 원천이 다르다: transcript는 raw timestamp segment, description은 원문
    description substring, visual은 frame asset ID·timestamp·OCR region. 이번 작업은
    transcript만 실검증하고 다른 source_kind는 `not_applicable`로 둔다(후속 T-168/T-173).

    LLM 자가 보고 confidence는 이 상태 판정에 절대 쓰지 않는다(가짜 정밀도 방지).
    """

    # quote가 raw timestamp segment 텍스트에 실존(공백 정규화 후 부분 문자열 일치).
    VERIFIED_RAW = "verified_raw"
    # quote가 raw segment에 없음(변형/창작 인용 포함) — 자동확정·export 차단.
    UNVERIFIED = "unverified"
    # 모델이 근거(quote)를 주지 않음 — 자동확정·export 차단.
    MISSING = "missing"
    # source 특성상 raw segment grounding을 적용하지 않음(비-transcript 등, 후속 규칙).
    NOT_APPLICABLE = "not_applicable"
    # 이 게이트 도입 이전에 생성된 기존 후보 — 자동 신뢰 금지, 재처리 또는 사람 검수 요구.
    LEGACY_UNKNOWN = "legacy_unknown"

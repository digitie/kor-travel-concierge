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

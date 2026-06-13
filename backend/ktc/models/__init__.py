"""SQLAlchemy 2.0 모델 패키지.

`docs/architecture.md` 6장 엔티티 구조를 구현한다.

공통 작업/감사/설정(T-004):
    - crawl_runs, audit_logs, system_settings

공간/도메인 데이터(T-005):
    - search_keywords, source_targets, youtube_videos, travel_places,
      extracted_place_candidates, video_place_mappings, media_assets

`travel_places.geom`은 PostGIS `geometry(Point, 4326)` 컬럼이다(ADR-25).
"""

from __future__ import annotations

from ktc.models.audit_log import AuditLog
from ktc.models.base import Base, TimestampMixin, utcnow
from ktc.models.crawl_run import CrawlRun, RunSource, RunState
from ktc.models.extracted_place_candidate import ExtractedPlaceCandidate, MatchStatus
from ktc.models.feature_evidence import EvidenceSourceKind, FeatureExportStatus
from ktc.models.feature_export import (
    FeatureExport,
    FeatureExportOperation,
    feature_export_sequence,
)
from ktc.models.media_asset import AssetType, MediaAsset
from ktc.models.search_keyword import SearchKeyword
from ktc.models.source_target import SourceTarget, TargetType
from ktc.models.system_setting import SystemSetting
from ktc.models.travel_place import DescriptionReviewStatus, TravelPlace
from ktc.models.video_place_mapping import VideoPlaceMapping
from ktc.models.youtube_channel import YoutubeChannel
from ktc.models.youtube_playlist import YoutubePlaylist
from ktc.models.youtube_playlist_video import YoutubePlaylistVideo
from ktc.models.youtube_video import CrawlStatus, YoutubeVideo
from ktc.models.youtube_video_analysis_run import (
    VideoAnalysisRunState,
    VideoAnalysisRunType,
    YoutubeVideoAnalysisRun,
)

__all__ = [
    # 공통 기반
    "Base",
    "TimestampMixin",
    "utcnow",
    # 작업/감사/설정
    "CrawlRun",
    "RunState",
    "RunSource",
    "AuditLog",
    "SystemSetting",
    # 도메인/공간
    "SearchKeyword",
    "SourceTarget",
    "TargetType",
    "YoutubeVideo",
    "CrawlStatus",
    "YoutubeChannel",
    "YoutubePlaylist",
    "YoutubePlaylistVideo",
    "YoutubeVideoAnalysisRun",
    "VideoAnalysisRunType",
    "VideoAnalysisRunState",
    "TravelPlace",
    "DescriptionReviewStatus",
    "ExtractedPlaceCandidate",
    "MatchStatus",
    "EvidenceSourceKind",
    "FeatureExportStatus",
    "FeatureExport",
    "FeatureExportOperation",
    "feature_export_sequence",
    "VideoPlaceMapping",
    "MediaAsset",
    "AssetType",
]

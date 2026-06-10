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

from app.models.audit_log import AuditLog
from app.models.base import Base, TimestampMixin, utcnow
from app.models.crawl_run import CrawlRun, RunSource, RunState
from app.models.extracted_place_candidate import ExtractedPlaceCandidate, MatchStatus
from app.models.media_asset import AssetType, MediaAsset
from app.models.search_keyword import SearchKeyword
from app.models.source_target import SourceTarget, TargetType
from app.models.system_setting import SystemSetting
from app.models.travel_place import DescriptionReviewStatus, TravelPlace
from app.models.video_place_mapping import VideoPlaceMapping
from app.models.youtube_channel import YoutubeChannel
from app.models.youtube_playlist import YoutubePlaylist
from app.models.youtube_playlist_video import YoutubePlaylistVideo
from app.models.youtube_video import CrawlStatus, YoutubeVideo
from app.models.youtube_video_analysis_run import (
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
    "VideoPlaceMapping",
    "MediaAsset",
    "AssetType",
]

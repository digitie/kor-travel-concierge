"""SQLAlchemy 2.0 모델 패키지.

`docs/architecture.md` 6장 엔티티 구조를 단계적으로 구현한다.

구현 완료(T-004 공통 작업/감사/설정):
    - crawl_runs              (web/mcp/scheduler 공유 작업 테이블)
    - audit_logs
    - system_settings

구현 대상(T-005 공간 데이터):
    - search_keywords
    - source_targets
    - youtube_videos          (description_raw / description_gemini_corrected 분리)
    - travel_places           (geom Point(4326), gemini_enriched_description)
    - extracted_place_candidates  (match_status, 검수 메타데이터)
    - video_place_mappings
    - media_assets            (RustFS 객체 URI·체크섬·보존 정책)
"""

from __future__ import annotations

from app.models.audit_log import AuditLog
from app.models.base import Base, TimestampMixin, utcnow
from app.models.crawl_run import CrawlRun, RunSource, RunState
from app.models.system_setting import SystemSetting

__all__ = [
    "Base",
    "TimestampMixin",
    "utcnow",
    "CrawlRun",
    "RunState",
    "RunSource",
    "AuditLog",
    "SystemSetting",
]

"""SQLAlchemy 2.0 모델 패키지 (스캐폴드).

`docs/architecture.md` 6장 엔티티 구조를 기준으로 T-004/T-005에서 다음 모델을
구현한다. 여기서는 공통 `Base`와 구현 목록만 정의한다.

구현 대상 테이블:
    - search_keywords
    - source_targets
    - youtube_videos          (description_raw / description_gemini_corrected 분리)
    - travel_places           (geom Point(4326), gemini_enriched_description)
    - extracted_place_candidates  (match_status, 검수 메타데이터)
    - video_place_mappings
    - media_assets            (RustFS 객체 URI·체크섬·보존 정책)
    - crawl_runs              (web/mcp/scheduler 공유 작업 테이블)
    - system_settings
    - audit_logs
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 ORM 모델의 공통 베이스."""


__all__ = ["Base"]

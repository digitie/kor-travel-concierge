"""`travel_places` 모델.

확정된 여행지를 저장한다. 좌표는 `latitude`/`longitude` 컬럼으로 보관하고,
PostGIS `geometry(Point, 4326)` `geom` 컬럼은 반경 검색과 중복 탐지에 사용한다.

장소 기본 설명(`description`)과 Gemini 보강 설명(`gemini_enriched_description`)을
분리 저장한다. (`docs/architecture.md` 4.4·6.4, ADR-16)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, TimestampMixin


class DescriptionReviewStatus(str, Enum):
    AI_GENERATED = "ai_generated"
    USER_REVIEWED = "user_reviewed"
    REJECTED = "rejected"


class TravelPlace(TimestampMixin, Base):
    __tablename__ = "travel_places"
    __table_args__ = (
        Index("ix_travel_places_geom_gist", "geom", postgresql_using="gist"),
        Index("ix_travel_places_sigungu_code", "sigungu_code"),
        Index("ix_travel_places_legal_dong_code", "legal_dong_code"),
    )

    place_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    gemini_enriched_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DescriptionReviewStatus.AI_GENERATED
    )
    official_address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    road_address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    geom: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )
    api_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category: Mapped[str] = mapped_column(
        String(64), nullable=False, default="unknown", server_default="unknown"
    )
    # `python-krtour-map` 8자리 category 코드 제안값(T-070). Gemini가 복사된 코드표에서
    # 고른 결과이며, feature export `category_code_suggestion`으로 노출한다.
    category_code_suggestion: Mapped[str] = mapped_column(
        String(16), nullable=False, default="0", server_default="0"
    )
    # kor-travel-geo v2 reverse 결과. 결과 필터와 외부 공급에서 행정구역 기준으로 쓴다.
    legal_dong_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    legal_dong_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sigungu_code: Mapped[str | None] = mapped_column(String(5), nullable=True)
    sigungu_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    admin_code_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    admin_code_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_geocoded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detailed_research_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

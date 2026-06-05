"""`travel_places` 모델.

확정된 여행지를 저장한다. 좌표는 `latitude`/`longitude` 컬럼으로 보관하고,
SpatiaLite Point(4326) `geom` 컬럼과 R-Tree 공간 인덱스는 ORM 밖에서
`app.core.spatial`이 SpatiaLite DDL로 관리한다(ADR-17).

장소 기본 설명(`description`)과 Gemini 보강 설명(`gemini_enriched_description`)을
분리 저장한다. (`docs/architecture.md` 4.4·6.4, ADR-16)
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DescriptionReviewStatus(StrEnum):
    AI_GENERATED = "ai_generated"
    USER_REVIEWED = "user_reviewed"
    REJECTED = "rejected"


class TravelPlace(TimestampMixin, Base):
    __tablename__ = "travel_places"

    place_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    gemini_enriched_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_review_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, default=DescriptionReviewStatus.AI_GENERATED
    )
    official_address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    road_address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    longitude: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    # geom: SpatiaLite Point(4326) — app.core.spatial이 DDL로 추가/동기화한다.
    api_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_geocoded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detailed_research_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

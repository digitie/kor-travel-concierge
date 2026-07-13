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
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    FetchedValue,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, TimestampMixin


class DescriptionReviewStatus(str, Enum):
    AI_GENERATED = "ai_generated"
    USER_REVIEWED = "user_reviewed"
    REJECTED = "rejected"


class PlaceLifecycleOrigin(str, Enum):
    """장소가 생성된 생명주기 경로.

    후보를 확정하며 생성한 장소만 원본 후보를 추적한다. 직접 생성하거나 후보와 독립적으로
    유지해야 하는 장소는 ``persistent``, 이 컬럼 도입 전 장소는 보수적으로
    ``legacy_unknown``으로 구분한다.
    """

    CANDIDATE_CREATED = "candidate_created"
    PERSISTENT = "persistent"
    LEGACY_UNKNOWN = "legacy_unknown"


class TravelPlace(TimestampMixin, Base):
    __tablename__ = "travel_places"
    __table_args__ = (
        Index("ix_travel_places_geom_gist", "geom", postgresql_using="gist"),
        Index("ix_travel_places_sigungu_code", "sigungu_code"),
        Index("ix_travel_places_legal_dong_code", "legal_dong_code"),
        Index("ix_travel_places_origin_candidate_id", "origin_candidate_id"),
        CheckConstraint(
            "lifecycle_origin IN "
            "('candidate_created', 'persistent', 'legacy_unknown')",
            name="ck_travel_places_lifecycle_origin",
        ),
        CheckConstraint(
            "(lifecycle_origin = 'candidate_created' "
            "AND origin_candidate_id IS NOT NULL) OR "
            "(lifecycle_origin IN ('persistent', 'legacy_unknown') "
            "AND origin_candidate_id IS NULL)",
            name="ck_travel_places_origin_candidate_consistency",
        ),
        CheckConstraint(
            "state_revision > 0",
            name="ck_travel_places_state_revision_positive",
        ),
    )

    place_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lifecycle_origin: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PlaceLifecycleOrigin.PERSISTENT.value,
        server_default=PlaceLifecycleOrigin.PERSISTENT.value,
    )
    origin_candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "extracted_place_candidates.id",
            name="fk_travel_places_origin_candidate_id_epc",
            ondelete="NO ACTION",
            use_alter=True,
        ),
        nullable=True,
    )
    state_revision: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
        server_default="1",
        server_onupdate=FetchedValue(),
    )
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

"""`search_keywords` 모델.

시드 키워드와 Gemini가 생성한 파생 키워드를 1:N으로 저장한다. 파생 시점의
계절 맥락을 `season_context`에 남긴다. (`docs/architecture.md` 4.1·6.1)
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, TimestampMixin


class SearchKeyword(TimestampMixin, Base):
    __tablename__ = "search_keywords"
    __table_args__ = (
        UniqueConstraint(
            "seed_keyword",
            "derived_keyword",
            "season_context",
            name="uq_search_keywords_seed_derived_season",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seed_keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    derived_keyword: Mapped[str | None] = mapped_column(String(255), nullable=True)
    season_context: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

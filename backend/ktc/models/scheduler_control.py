"""실행 방식과 전환 세대의 DB 정본. 환경변수로 두 실행자를 동시에 켜지 않는다."""

from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base


class SchedulerControl(Base):
    __tablename__ = "scheduler_control"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_scheduler_control_singleton"),
        CheckConstraint(
            "backend IN ('legacy', 'dagster')", name="ck_scheduler_control_backend"
        ),
        CheckConstraint("generation >= 0", name="ck_scheduler_control_generation"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    backend: Mapped[str] = mapped_column(String(16), nullable=False, default="legacy")
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

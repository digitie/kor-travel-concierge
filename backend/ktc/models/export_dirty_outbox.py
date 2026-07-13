"""feature export durable dirty outbox 모델 (T-171, S6/A2).

`feature_exports` ledger는 후보 상태로부터 멱등 동기화되는데, 매 공급 GET마다 전 후보를
재동기화하면 소비자 폴링 비용이 후보 수에 비례한다. 이를 없애기 위해, export payload에
영향을 주는 변경(후보 상태 전이·삭제·tombstone·장소/영상 정리 등)을 **변경과 같은
트랜잭션**에서 이 outbox에 기록하고, 공급 GET은 outbox에 실린 후보만 동기화(consume)한다.

process-local 스로틀·`updated_at` 워터마크·모듈 상태 플래그가 아니라 DB durable 테이블인
이유: API와 scheduler가 별도 프로세스이고 재시작이 잦아, 그런 프로세스-로컬 상태는 두
프로세스·재시작에서 정본이 될 수 없다(로드맵 PR-22 개정 2026-07-13, §10.4).

컬럼:
- `candidate_id`: 변경된 후보 id(PK). 같은 후보가 다시 바뀌면 upsert로 마지막 사유가
  이긴다(자가 dedup). sync는 멱등이라 경계 중복(같은 후보가 여러 번 실린 채 처리돼도)
  안전하다.
- `reason`: 진단용 마지막 변경 사유(예: `resolve`, `soft_delete`, `geocode_apply`).
- `marked_at`: 마지막으로 dirty 표시된 시각(진단·관측용).

FK는 `extracted_place_candidates.id`(`ondelete=CASCADE`)로 둔다. 후보는 hard delete되지
않지만(soft delete만), 방어적으로 CASCADE를 걸어 후보가 사라지면 outbox 행도 정리한다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, utcnow


class ExportDirtyOutbox(Base):
    __tablename__ = "export_dirty_outbox"

    candidate_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("extracted_place_candidates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    marked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )

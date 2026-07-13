"""provider별 지오코딩 응답 캐시 모델 (T-170, S7).

같은 장소가 여러 영상에 반복 등장할 때 지오코딩 provider를 매번 재호출하는 문제를
줄이기 위한 DB 캐시다. API 프로세스와 scheduler 프로세스가 같은 캐시를 공유해야 하므로
프로세스 로컬 dict가 아니라 DB 테이블로 둔다.

**정책 제약**: `docs/provider-policy.md`의 provider policy matrix에서 캐싱이 허용된
provider(현재 Kakao Local뿐)만 저장한다. VWorld("실시간 사용, DB 저장 불가")와
Naver(NCP Maps 제7조⑨·⑪, Developers Local Search 7.3.③ — 캐시 포함 금지)는 정책상
캐시 대상이 아니다. 저장 여부 판단은 `ktc.etl.geocoding`의 provider allowlist가 관장하고,
이 모델은 순수 저장 구조만 정의한다.

컬럼:
- `query_hash`: `sha256(provider|endpoint|canonical_params|NORMALIZATION_VERSION)` (PK).
- `provider`: 캐시된 provider 식별자(정책 allowlist 키, 예: `kakao`).
- `response_class`: 성공 4분류 중 저장 가능한 값(`success_nonempty`|`success_empty`).
  error(transient/permanent)는 저장하지 않으므로 이 컬럼에는 성공 분류만 들어온다.
- `results_json`: provider 결과를 정책 allowed_fields로 필터링한 후보 dict 배열(JSONB).
- `created_at`: 저장 시각. lazy TTL 만료 판정 기준(정리 스케줄러 없음, 조회 시 무시·덮어씀).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ktc.models.base import Base, utcnow


class GeocodeCache(Base):
    __tablename__ = "geocode_cache"

    query_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    response_class: Mapped[str] = mapped_column(String(16), nullable=False)
    results_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

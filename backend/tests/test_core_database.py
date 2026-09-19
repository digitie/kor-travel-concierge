"""`ktc.core.database.create_engine()` 연결 풀 설정 테스트.

엔진 생성은 실제 연결을 만들지 않는(lazy) 동작이라 DB 없이도 검증할 수 있다.
"""

from __future__ import annotations

from ktc.core import database
from ktc.core.config import Settings


def test_create_engine_uses_default_pool_settings(monkeypatch):
    """DATABASE_POOL_SIZE/MAX_OVERFLOW 미설정 시 SQLAlchemy 기본값과 같아야 한다
    (기존 동작 변화 없음 — kor-travel-docker-manager 저장소 docs/platform-topology.md
    §7의 공용 Postgres 인스턴스 전환을 대비해 환경변수화만 했을 뿐, 지금은 하드코딩과
    동일한 값이어야 한다)."""
    settings = Settings(DATABASE_URL="postgresql+asyncpg://addr:addr@localhost/test")
    monkeypatch.setattr(database, "get_settings", lambda: settings)

    engine = database.create_engine()
    try:
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 10
    finally:
        # 실제 연결을 만들지 않았으므로 dispose는 동기 정리만 수행한다.
        engine.sync_engine.dispose()


def test_create_engine_respects_configured_pool_settings(monkeypatch):
    """공용 인스턴스로 옮긴 뒤에는 배포 설정만으로 프로젝트별 풀 예산을 좁힐 수
    있어야 한다."""
    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://addr:addr@localhost/test",
        DATABASE_POOL_SIZE=2,
        DATABASE_MAX_OVERFLOW=3,
    )
    monkeypatch.setattr(database, "get_settings", lambda: settings)

    engine = database.create_engine()
    try:
        assert engine.pool.size() == 2
        assert engine.pool._max_overflow == 3
    finally:
        engine.sync_engine.dispose()

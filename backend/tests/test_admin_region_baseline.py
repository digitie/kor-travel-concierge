"""첫 토큰 기준선: 소유 in-memory SQLite 설정 테이블에서 원자 저장을 검사한다.

PostGIS/place 경로는 기존 test_admin_region_refresh.py가 담당한다.
이 파일은 외부 DB/HTTP 없이 실제 설정 INSERT/RETURNING/rollback을 실행한다.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from ktc.etl import admin_region_refresh as refresh
from ktc.models import SystemSetting
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

TOKEN = "dd1-" + "a" * 32
OTHER = "dd1-" + "b" * 32
MARKER = {"token": TOKEN, "after": 0, "ceiling": None, "phase": "baseline"}


@pytest.fixture
def settings_db():
    engine = create_engine("sqlite:///:memory:")
    SystemSetting.__table__.create(engine)
    # 재개 분기의 빈 keyset 상한 조회에 필요한 열만 소유 scratch에 둔다.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE travel_places (place_id INTEGER, is_geocoded BOOLEAN, "
            "admin_code_geo_data_token VARCHAR)"
        )
        conn.exec_driver_sql("INSERT INTO travel_places VALUES (1, 1, NULL)")

    class AsyncSettingsSession:
        def __init__(self, session):
            self.session = session

        async def get(self, *args, **kwargs):
            return self.session.get(*args, **kwargs)

        async def scalar(self, statement):
            return self.session.scalar(statement)

        async def execute(self, statement):
            return self.session.execute(statement)

        async def scalars(self, statement):
            return self.session.scalars(statement)

        async def commit(self):
            self.session.commit()

        async def rollback(self):
            self.session.rollback()

    @asynccontextmanager
    async def factory():
        with Session(engine) as session:
            yield AsyncSettingsSession(session)

    yield engine, factory
    engine.dispose()


def stored(engine):
    with Session(engine) as session:
        return {row.key: row.value for row in session.query(SystemSetting).all()}


def put(engine, key, value):
    with Session(engine) as session:
        session.add(SystemSetting(key=key, value=value))
        session.commit()


async def tick(factory, monkeypatch, *, token=TOKEN, stale=True):
    async def current(*args):
        return token

    async def has_stale(*args):
        return stale

    async def forbidden(*args, **kwargs):
        pytest.fail("기준선 tick은 장소 재해결/진척 저장을 호출하면 안 된다")

    monkeypatch.setattr(refresh, "current_token", current)
    monkeypatch.setattr(refresh, "stale_exists", has_stale)
    monkeypatch.setattr(refresh, "refresh_place_admin_codes_isolated", forbidden)
    return await refresh._refresh(
        factory,
        SimpleNamespace(),
        None,
        "http://unused.test",
        "fixture",
        refresh.RefreshStats(),
    )


async def test_first_two_ticks_keep_stale_places_uninterpreted(
    settings_db, monkeypatch
):
    engine, factory = settings_db
    first = await tick(factory, monkeypatch)
    assert first.metadata() == {
        "state": "baseline",
        "scanned": 0,
        "resolved": 0,
        "unresolved": 0,
        "errored": 0,
        "skipped": 0,
        "dirty": 0,
        "token_advanced": True,
    }
    before = stored(engine)
    assert before[refresh.CURSOR_KEY] == TOKEN
    assert json.loads(before[refresh.PROGRESS_KEY]) == MARKER
    second = await tick(factory, monkeypatch)
    assert second.state == "noop" and second.scanned == second.dirty == 0
    assert not second.token_advanced and stored(engine) == before


@pytest.mark.parametrize("key", [refresh.CURSOR_KEY, refresh.PROGRESS_KEY])
async def test_insert_conflict_never_overwrites_and_rolls_back_first_claim(
    settings_db, key
):
    engine, factory = settings_db
    put(engine, key, "concurrent-owner")
    assert not await refresh.claim_baseline(factory, TOKEN)
    assert stored(engine) == {key: "concurrent-owner"}


async def test_lost_claim_after_initial_read_does_not_reinterpret(
    settings_db, monkeypatch
):
    engine, factory = settings_db
    original = refresh.claim_baseline

    async def raced_claim(factory, token):
        put(engine, refresh.CURSOR_KEY, OTHER)
        return await original(factory, token)

    monkeypatch.setattr(refresh, "claim_baseline", raced_claim)
    result = await tick(factory, monkeypatch)
    assert result.state == "pending" and not result.token_advanced
    assert stored(engine) == {refresh.CURSOR_KEY: OTHER}


async def test_second_insert_failure_does_not_leave_half_baseline(
    settings_db, monkeypatch
):
    engine, factory = settings_db
    from sqlalchemy import event

    def reject_cursor(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT") and refresh.CURSOR_KEY in parameters:
            raise RuntimeError("fixture second-write failure")

    event.listen(engine, "before_cursor_execute", reject_cursor)
    try:
        with pytest.raises(RuntimeError, match="fixture"):
            await tick(factory, monkeypatch)
    finally:
        event.remove(engine, "before_cursor_execute", reject_cursor)
    assert stored(engine) == {}


@pytest.mark.parametrize("previous", [None, OTHER])
async def test_marker_without_matching_cursor_does_not_suppress_resume(
    settings_db, monkeypatch, previous
):
    engine, factory = settings_db
    put(engine, refresh.PROGRESS_KEY, json.dumps(MARKER))
    if previous is not None:
        put(engine, refresh.CURSOR_KEY, previous)

    async def resumed(*args):
        raise RuntimeError("fixture existing resume reached")

    monkeypatch.setattr(refresh, "save_progress", resumed)
    # 기존 progress가 있으면 baseline으로 덮지 않고 정상 sweep 준비까지 진행한다.
    with pytest.raises(RuntimeError, match="fixture existing resume"):
        await tick(factory, monkeypatch)
    assert json.loads(stored(engine)[refresh.PROGRESS_KEY]) == MARKER


@pytest.mark.parametrize(
    "change",
    [
        {"phase": "unknown"},
        {"after": 1},
        {"after": True},
        {"ceiling": 0},
        {"token": "bad"},
        {"extra": 1},
    ],
)
async def test_malformed_baseline_fails_before_place_work(
    settings_db, monkeypatch, change
):
    engine, factory = settings_db
    put(engine, refresh.CURSOR_KEY, TOKEN)
    put(engine, refresh.PROGRESS_KEY, json.dumps(MARKER | change))
    before = stored(engine)
    with pytest.raises(refresh.RefreshError):
        await tick(factory, monkeypatch)
    assert stored(engine) == before


async def test_no_current_token_writes_neither_key(settings_db, monkeypatch):
    engine, factory = settings_db
    result = await tick(factory, monkeypatch, token=None)
    assert result.state == "data_token_unavailable" and stored(engine) == {}


def test_changed_release_resets_baseline_and_keeps_legacy_progress():
    raw = json.dumps(MARKER)
    assert refresh.read_progress(raw, OTHER) == (0, None, False)
    assert refresh.read_progress(json.dumps({"token": TOKEN, "after": 7}), TOKEN) == (
        7,
        None,
        False,
    )

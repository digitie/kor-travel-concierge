"""릴리스별 행정구역 재해결. 짧은 세션·ID keyset·장소별 commit으로 재개한다."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ktc.core.config import Settings
from ktc.etl.admin_region_service import (
    GEO_HTTP_TIMEOUT,
    parse_data_token,
    refresh_place_admin_codes_isolated,
)
from ktc.models import SystemSetting, TravelPlace, utcnow
from ktc.services.settings_service import get_secret, get_setting

CURSOR_KEY = "kor_travel_geo_data_token"
PAGE_SIZE = 50


@dataclass
class RefreshStats:
    state: str = "pending"
    scanned: int = 0
    resolved: int = 0
    unresolved: int = 0
    errored: int = 0
    skipped: int = 0
    dirty: int = 0
    token_advanced: bool = False

    def metadata(self) -> dict[str, str | int | bool]:
        return asdict(self)


class RefreshError(RuntimeError):
    """Dagster 경계에서 실패로 표시할 오류. URL·키·HTTP 본문은 포함하지 않는다."""

    def __init__(self, message: str, stats: RefreshStats) -> None:
        super().__init__(message)
        self.stats = stats


def stale_condition(token: str):
    return (
        TravelPlace.is_geocoded.is_(True),
        TravelPlace.admin_code_geo_data_token.is_distinct_from(token),
    )


async def stale_exists(session: AsyncSession, token: str) -> bool:
    return (
        await session.scalar(
            select(TravelPlace.place_id).where(*stale_condition(token)).limit(1)
        )
        is not None
    )


async def current_token(
    client: httpx.AsyncClient, base_url: str, api_key: str
) -> str | None:
    response = await client.post(
        base_url.rstrip("/") + "/v2/dataset/version",
        headers={"X-KTG-API-Key": api_key},
        json={},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("status") not in {
        "OK",
        "NOT_FOUND",
    }:
        raise ValueError("geo 버전 응답 형식 오류")
    if not isinstance(payload.get("available"), bool):
        raise TypeError("geo 버전 available 형식 오류")
    current = payload.get("current")
    if current is None and payload["available"] is False:
        return None
    if not isinstance(current, dict) or payload["available"] is False:
        raise ValueError("geo 현재 릴리스 형식 오류")
    token = current.get("data_token")
    if token is None:
        return None
    if parse_data_token(token) != token:
        raise ValueError("geo 데이터 토큰 형식 오류")
    return token


async def refresh_admin_regions(
    factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
) -> RefreshStats:
    stats = RefreshStats()
    base_url = settings.KOR_TRAVEL_GEO_V2_BASE_URL.strip()
    async with factory() as session:
        api_key = await get_secret(session, "kor_travel_geo_v2_api_key")
        await session.commit()
    if not base_url or not api_key:
        stats.state = "not_configured"
        return stats
    # 단일 순차 client를 재사용한다. 각 HTTP 요청 중 DB transaction/connection은 없다.
    if http_client is None:
        async with httpx.AsyncClient(
            timeout=GEO_HTTP_TIMEOUT,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        ) as client:
            return await _refresh(factory, settings, client, base_url, api_key, stats)
    return await _refresh(factory, settings, http_client, base_url, api_key, stats)


async def _refresh(factory, settings, client, base_url, api_key, stats):
    try:
        token = await current_token(client, base_url, api_key)
    except Exception as error:  # noqa: BLE001 - 공개 I/O 실패를 키/URL 없이 op 실패로 전달
        raise RefreshError(
            f"geo 버전 조회 실패 ({type(error).__name__})", stats
        ) from None
    if token is None:
        stats.state = "data_token_unavailable"
        return stats
    async with factory() as session:
        previous = await get_setting(session, CURSOR_KEY)
        stale = await stale_exists(session, token)
        await session.commit()
    if previous == token and not stale:
        stats.state = "noop"
        return stats

    after = 0
    while True:
        async with factory() as session:
            ids = list(
                (
                    await session.scalars(
                        select(TravelPlace.place_id)
                        .where(TravelPlace.place_id > after, *stale_condition(token))
                        .order_by(TravelPlace.place_id)
                        .limit(PAGE_SIZE)
                    )
                ).all()
            )
            await session.commit()
        if not ids:
            break
        for place_id in ids:
            after = place_id
            result = await refresh_place_admin_codes_isolated(
                factory,
                place_id,
                data_token=token,
                settings=settings,
                http_client=client,
            )
            stats.scanned += 1
            setattr(stats, result.outcome, getattr(stats, result.outcome) + 1)
            stats.dirty += int(result.dirty)

    attempted = stats.resolved + stats.unresolved + stats.errored
    if (
        attempted >= PAGE_SIZE
        and stats.errored / attempted > settings.ADMIN_REGION_REFRESH_ERROR_RATIO
    ):
        raise RefreshError("행정구역 재해결 오류 비율이 문턱을 초과했습니다", stats)
    # keyset 순회 끝만으로 전진하지 않는다. 오류·fence drift·새 stale 행을 다시 본다.
    async with factory() as session:
        if await stale_exists(session, token):
            await session.commit()
            return stats
        await session.execute(
            insert(SystemSetting)
            .values(key=CURSOR_KEY, value=token, updated_at=utcnow())
            .on_conflict_do_update(
                index_elements=[SystemSetting.key],
                set_={"value": token, "updated_at": utcnow()},
            )
        )
        await session.commit()
    stats.token_advanced = previous != token
    stats.state = "completed"
    return stats

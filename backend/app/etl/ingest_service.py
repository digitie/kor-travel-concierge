"""수집 결과 영속화 서비스.

`video_id` 기준 멱등 upsert, 파생 키워드 저장, 채널 워터마크(최신 업로드 시각)
조회를 담당한다(`docs/architecture.md` 4.2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SearchKeyword, YoutubeVideo


def parse_published_at(value: str | None) -> datetime | None:
    """ISO 8601(예: `2026-05-01T12:00:00Z`) 문자열을 timezone-aware로 파싱한다."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def persist_derived_keywords(
    session: AsyncSession, *, seed: str, derived: list[str], season: str
) -> list[SearchKeyword]:
    """시드와 파생 키워드를 `search_keywords`에 1:N으로 저장한다."""
    if not derived:
        return []

    stmt = select(SearchKeyword).where(
        SearchKeyword.seed_keyword == seed,
        SearchKeyword.season_context == season,
        SearchKeyword.derived_keyword.in_(derived),
    )
    result = await session.execute(stmt)
    existing_by_keyword = {
        row.derived_keyword: row for row in result.scalars().all() if row.derived_keyword
    }

    rows: list[SearchKeyword] = []
    new_rows: list[SearchKeyword] = []
    for keyword in derived:
        existing = existing_by_keyword.get(keyword)
        if existing is not None:
            rows.append(existing)
            continue
        row = SearchKeyword(
            seed_keyword=seed,
            derived_keyword=keyword,
            season_context=season,
        )
        rows.append(row)
        new_rows.append(row)

    if new_rows:
        session.add_all(new_rows)
        await session.commit()
    return rows


async def get_channel_watermark(
    session: AsyncSession, channel_id: str
) -> datetime | None:
    """채널의 가장 최신 영상 업로드 시각(워터마크)을 반환한다.

    다음 크롤에서 이 시각 이후 영상만 처리하도록 `publishedAfter` 필터에 쓴다.
    """
    stmt = select(func.max(YoutubeVideo.published_at)).where(
        YoutubeVideo.channel_id == channel_id
    )
    result = await session.execute(stmt)
    return result.scalar()


async def upsert_video(
    session: AsyncSession, candidate: dict[str, Any]
) -> tuple[YoutubeVideo, bool]:
    """`video_id` 기준 멱등 upsert. `(video, created)` 반환."""
    video_id = candidate["video_id"]
    existing = await session.get(YoutubeVideo, video_id)
    fields = dict(
        title=candidate.get("title", ""),
        url=candidate.get("url", f"https://youtu.be/{video_id}"),
        channel_id=candidate.get("channel_id", ""),
        channel_name=candidate.get("channel_name"),
        published_at=candidate.get("published_at"),
        view_count=candidate.get("view_count"),
        like_count=candidate.get("like_count"),
        engagement_score=candidate.get("engagement_score"),
        description_raw=candidate.get("description_raw"),
    )
    if existing is None:
        video = YoutubeVideo(video_id=video_id, **fields)
        session.add(video)
        await session.commit()
        await session.refresh(video)
        return video, True

    # 멱등: 통계/메타데이터를 갱신하되 Gemini 보정 필드는 건드리지 않는다.
    for key, value in fields.items():
        if value is not None:
            setattr(existing, key, value)
    await session.commit()
    await session.refresh(existing)
    return existing, False


async def ingest_candidates(
    session: AsyncSession, candidates: list[dict[str, Any]]
) -> dict[str, int]:
    """후보 목록을 멱등 적재하고 요약을 반환한다."""
    inserted = 0
    updated = 0
    for candidate in candidates:
        _, created = await upsert_video(session, candidate)
        if created:
            inserted += 1
        else:
            updated += 1
    return {
        "discovered": len(candidates),
        "inserted": inserted,
        "updated": updated,
    }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

"""수집 결과 영속화 서비스.

`video_id` 기준 멱등 upsert, 파생 키워드 저장, 채널 워터마크(최신 업로드 시각)
조회를 담당한다(`docs/architecture.md` 4.2).
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.models import (
    SearchKeyword,
    SourceTarget,
    YoutubeChannel,
    YoutubePlaylist,
    YoutubePlaylistVideo,
    YoutubeVideo,
)

_YOUTUBE_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


def parse_published_at(value: str | None) -> datetime | None:
    """ISO 8601(예: `2026-05-01T12:00:00Z`) 문자열을 timezone-aware로 파싱한다."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_duration_seconds(value: str | None) -> int | None:
    """YouTube ISO 8601 duration(`PT1H2M3S`)을 초 단위로 변환한다."""
    if not value:
        return None
    match = _YOUTUBE_DURATION_RE.match(value)
    if not match:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return (days * 86_400) + (hours * 3_600) + (minutes * 60) + seconds


def best_thumbnail_url(thumbnails: dict[str, Any] | None) -> str | None:
    """YouTube thumbnails 객체에서 가장 큰 대표 URL을 고른다."""
    if not isinstance(thumbnails, dict):
        return None
    for key in ("maxres", "standard", "high", "medium", "default"):
        item = thumbnails.get(key)
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            return item["url"]
    return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_channel_metadata(item: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """`channels.list` item을 `youtube_channels` upsert payload로 변환한다."""
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    channel_id = str(item.get("id") or "")
    return {
        "channel_id": channel_id,
        "title": snippet.get("title") or channel_id,
        "handle": snippet.get("customUrl"),
        "custom_url": snippet.get("customUrl"),
        "description": snippet.get("description"),
        "thumbnail_url": best_thumbnail_url(snippet.get("thumbnails")),
        "subscriber_count": _to_int(statistics.get("subscriberCount")),
        "video_count": _to_int(statistics.get("videoCount")),
        "published_at": parse_published_at(snippet.get("publishedAt")),
        "last_seen_at": now,
    }


def build_playlist_metadata(item: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """`playlists.list` item을 `youtube_playlists` upsert payload로 변환한다."""
    snippet = item.get("snippet", {})
    content_details = item.get("contentDetails", {})
    playlist_id = str(item.get("id") or "")
    return {
        "playlist_id": playlist_id,
        "channel_id": snippet.get("channelId") or "",
        "title": snippet.get("title") or playlist_id,
        "description": snippet.get("description"),
        "thumbnail_url": best_thumbnail_url(snippet.get("thumbnails")),
        "item_count": _to_int(content_details.get("itemCount")),
        "published_at": parse_published_at(snippet.get("publishedAt")),
        "last_crawled_at": now,
    }


def build_playlist_video_link(
    item: dict[str, Any],
    *,
    playlist_id: str,
    now: datetime,
) -> dict[str, Any] | None:
    """`playlistItems.list` item을 연결 테이블 payload로 변환한다."""
    snippet = item.get("snippet", {})
    content_details = item.get("contentDetails", {})
    video_id = content_details.get("videoId") or snippet.get("resourceId", {}).get("videoId")
    if not video_id:
        return None
    return {
        "playlist_id": playlist_id,
        "video_id": video_id,
        "position": _to_int(snippet.get("position")),
        "playlist_item_id": item.get("id"),
        "added_at": parse_published_at(snippet.get("publishedAt")),
        "first_seen_at": now,
        "last_seen_at": now,
    }


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


async def get_source_target_watermark(
    session: AsyncSession, *, target_type: str, source_value: str
) -> datetime | None:
    """수집 대상의 마지막 성공 크롤 시각을 반환한다."""
    stmt = select(SourceTarget.last_crawled_at).where(
        SourceTarget.target_type == target_type,
        SourceTarget.source_value == source_value,
    )
    result = await session.execute(stmt)
    return result.scalar()


async def mark_source_target_crawled(
    session: AsyncSession,
    *,
    target_type: str,
    source_value: str,
    crawled_at: datetime,
) -> SourceTarget:
    """수집 대상의 마지막 성공 크롤 시각을 갱신한다."""
    stmt = select(SourceTarget).where(
        SourceTarget.target_type == target_type,
        SourceTarget.source_value == source_value,
    )
    result = await session.execute(stmt)
    target = result.scalar_one_or_none()
    if target is None:
        target = SourceTarget(target_type=target_type, source_value=source_value)
        session.add(target)

    target.last_crawled_at = crawled_at
    if target_type == "playlist":
        playlist = await session.get(YoutubePlaylist, source_value)
        if playlist is not None:
            playlist.last_crawled_at = crawled_at
    await session.commit()
    await session.refresh(target)
    return target


async def ensure_channel_stub(
    session: AsyncSession,
    *,
    channel_id: str,
    title: str | None = None,
) -> YoutubeChannel | None:
    """영상 FK를 위해 최소 채널 행을 보장한다."""
    if not channel_id:
        return None
    channel = await session.get(YoutubeChannel, channel_id)
    if channel is not None:
        if title and channel.title == channel.channel_id:
            channel.title = title
        return channel
    channel = YoutubeChannel(
        channel_id=channel_id,
        title=title or channel_id,
        last_seen_at=utcnow(),
    )
    session.add(channel)
    await session.flush()
    return channel


async def upsert_channel(
    session: AsyncSession,
    payload: dict[str, Any],
) -> tuple[YoutubeChannel | None, bool]:
    """`channel_id` 기준 채널 metadata를 멱등 upsert한다."""
    channel_id = str(payload.get("channel_id") or "")
    if not channel_id:
        return None, False
    existing = await session.get(YoutubeChannel, channel_id)
    fields = {
        "title": payload.get("title") or channel_id,
        "handle": payload.get("handle"),
        "custom_url": payload.get("custom_url"),
        "description": payload.get("description"),
        "thumbnail_url": payload.get("thumbnail_url"),
        "subscriber_count": payload.get("subscriber_count"),
        "video_count": payload.get("video_count"),
        "published_at": payload.get("published_at"),
        "last_seen_at": payload.get("last_seen_at") or utcnow(),
    }
    if existing is None:
        channel = YoutubeChannel(channel_id=channel_id, **fields)
        session.add(channel)
        await session.commit()
        await session.refresh(channel)
        return channel, True

    for key, value in fields.items():
        if value is not None and value != "":
            setattr(existing, key, value)
    await session.commit()
    await session.refresh(existing)
    return existing, False


async def upsert_playlist(
    session: AsyncSession,
    payload: dict[str, Any],
) -> tuple[YoutubePlaylist | None, bool]:
    """`playlist_id` 기준 재생목록 metadata를 멱등 upsert한다."""
    playlist_id = str(payload.get("playlist_id") or "")
    channel_id = str(payload.get("channel_id") or "")
    if not playlist_id or not channel_id:
        return None, False
    await ensure_channel_stub(session, channel_id=channel_id)
    existing = await session.get(YoutubePlaylist, playlist_id)
    fields = {
        "channel_id": channel_id,
        "title": payload.get("title") or playlist_id,
        "description": payload.get("description"),
        "thumbnail_url": payload.get("thumbnail_url"),
        "item_count": payload.get("item_count"),
        "published_at": payload.get("published_at"),
        "last_crawled_at": payload.get("last_crawled_at"),
        "last_item_published_at": payload.get("last_item_published_at"),
    }
    if existing is None:
        playlist = YoutubePlaylist(playlist_id=playlist_id, **fields)
        session.add(playlist)
        await session.commit()
        await session.refresh(playlist)
        return playlist, True

    for key, value in fields.items():
        if value is not None and value != "":
            setattr(existing, key, value)
    await session.commit()
    await session.refresh(existing)
    return existing, False


async def upsert_video(
    session: AsyncSession, candidate: dict[str, Any]
) -> tuple[YoutubeVideo, bool]:
    """`video_id` 기준 멱등 upsert. `(video, created)` 반환."""
    video_id = candidate["video_id"]
    await ensure_channel_stub(
        session,
        channel_id=str(candidate.get("channel_id") or ""),
        title=candidate.get("channel_name"),
    )
    existing = await session.get(YoutubeVideo, video_id)
    fields = dict(
        title=candidate.get("title", ""),
        url=candidate.get("url", f"https://youtu.be/{video_id}"),
        channel_id=candidate.get("channel_id", ""),
        channel_name=candidate.get("channel_name"),
        published_at=candidate.get("published_at"),
        canonical_url=candidate.get("canonical_url"),
        duration_seconds=candidate.get("duration_seconds"),
        thumbnail_url=candidate.get("thumbnail_url"),
        default_language=candidate.get("default_language"),
        tags_json=candidate.get("tags_json"),
        source_target_type=candidate.get("source_target_type"),
        source_target_value=candidate.get("source_target_value"),
        source_search_query=candidate.get("source_search_query"),
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
        if value is not None and value != "":
            setattr(existing, key, value)
    await session.commit()
    await session.refresh(existing)
    return existing, False


async def upsert_playlist_video(
    session: AsyncSession,
    payload: dict[str, Any],
) -> tuple[YoutubePlaylistVideo | None, bool]:
    """재생목록-영상 연결을 멱등 upsert한다."""
    playlist_id = str(payload.get("playlist_id") or "")
    video_id = str(payload.get("video_id") or "")
    if not playlist_id or not video_id:
        return None, False
    playlist = await session.get(YoutubePlaylist, playlist_id)
    video = await session.get(YoutubeVideo, video_id)
    if playlist is None or video is None:
        return None, False
    existing = await session.get(YoutubePlaylistVideo, (playlist_id, video_id))
    fields = {
        "position": payload.get("position"),
        "playlist_item_id": payload.get("playlist_item_id"),
        "added_at": payload.get("added_at"),
        "last_seen_at": payload.get("last_seen_at") or utcnow(),
    }
    if existing is None:
        link = YoutubePlaylistVideo(
            playlist_id=playlist_id,
            video_id=video_id,
            position=payload.get("position"),
            playlist_item_id=payload.get("playlist_item_id"),
            added_at=payload.get("added_at"),
            first_seen_at=payload.get("first_seen_at") or utcnow(),
            last_seen_at=payload.get("last_seen_at") or utcnow(),
        )
        session.add(link)
        await session.commit()
        await session.refresh(link)
        return link, True

    for key, value in fields.items():
        if value is not None and value != "":
            setattr(existing, key, value)
    await session.commit()
    await session.refresh(existing)
    return existing, False


async def ingest_candidates(
    session: AsyncSession,
    candidates: list[dict[str, Any]],
    *,
    channels: list[dict[str, Any]] | None = None,
    playlists: list[dict[str, Any]] | None = None,
    playlist_links: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """후보 목록을 멱등 적재하고 요약을 반환한다."""
    channel_inserted = 0
    channel_updated = 0
    for payload in channels or []:
        channel, created = await upsert_channel(session, payload)
        if channel is None:
            continue
        if created:
            channel_inserted += 1
        else:
            channel_updated += 1

    inserted = 0
    updated = 0
    for candidate in candidates:
        _, created = await upsert_video(session, candidate)
        if created:
            inserted += 1
        else:
            updated += 1

    playlist_inserted = 0
    playlist_updated = 0
    for payload in playlists or []:
        playlist, created = await upsert_playlist(session, payload)
        if playlist is None:
            continue
        if created:
            playlist_inserted += 1
        else:
            playlist_updated += 1

    playlist_link_inserted = 0
    playlist_link_updated = 0
    for payload in playlist_links or []:
        link, created = await upsert_playlist_video(session, payload)
        if link is None:
            continue
        if created:
            playlist_link_inserted += 1
        else:
            playlist_link_updated += 1

    return {
        "discovered": len(candidates),
        "inserted": inserted,
        "updated": updated,
        "channels_inserted": channel_inserted,
        "channels_updated": channel_updated,
        "playlists_inserted": playlist_inserted,
        "playlists_updated": playlist_updated,
        "playlist_links_inserted": playlist_link_inserted,
        "playlist_links_updated": playlist_link_updated,
    }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

"""수집 영상 후처리 오케스트레이션.

`pipeline.run_harvest`가 YouTube 영상 후보를 `youtube_videos`에 적재한 뒤,
각 영상의 자막 확보, Gemini POI 추출, 지오코딩 적용까지 이어 붙인다. 외부
호출은 주입 가능하게 두어 테스트에서는 결정론적 fake로 검증하고, 운영에서는
설정된 Gemini/RustFS/VWorld/Kakao/Naver 키를 사용한다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from vworld import AsyncVworldClient

from app.core.config import Settings, get_settings
from app.etl import geocode_service, media_store, poi_extraction, summarize_service
from app.etl.geocoding import GeocodeDecision, KakaoGeocoder, NaverGeocoder
from app.etl.transcript import TranscriptResult, get_transcript_async
from app.models import (
    CrawlStatus,
    ExtractedPlaceCandidate,
    MatchStatus,
    TravelPlace,
    YoutubeVideo,
)
from app.services import settings_service

StatusReporter = Callable[[str, float | None], Awaitable[None]]
TranscriptFetcher = Callable[[str], Awaitable[TranscriptResult | None]]
GeocodeDecider = Callable[[ExtractedPlaceCandidate], Awaitable[GeocodeDecision]]
GeocodeApplier = Callable[
    [AsyncSession, ExtractedPlaceCandidate, GeocodeDecision],
    Awaitable[TravelPlace | None],
]


async def process_harvest_videos(
    session: AsyncSession,
    *,
    video_ids: Sequence[str] | None = None,
    limit: int | None = None,
    store: media_store.MediaStore | None = None,
    llm: poi_extraction.LlmCallable | None = None,
    transcript_fetcher: TranscriptFetcher | None = None,
    geocode_decider: GeocodeDecider | None = None,
    geocode_applier: GeocodeApplier | None = None,
    status_reporter: StatusReporter | None = None,
    max_retries: int = 2,
) -> dict[str, Any]:
    """수집 영상에서 장소 후보와 확정 장소를 생성한다.

    공급자별 실패는 전체 작업 실패로 전파하지 않고 영상 단위 실패로 집계한다.
    이렇게 해야 하나의 자막/Gemini/지오코딩 실패가 전체 harvest 큐를 막지 않는다.
    """
    settings = get_settings()
    videos = await _load_target_videos(session, video_ids=video_ids, limit=limit)
    resolved_store = store or _make_media_store(settings)

    summary = {
        "processed_videos": 0,
        "summarized_videos": 0,
        "failed_videos": 0,
        "skipped_videos": 0,
        "created_candidates": 0,
        "matched_places": 0,
        "needs_review_candidates": 0,
        "storage_mode": _storage_mode(resolved_store),
    }
    if not videos:
        await _report(status_reporter, "장소 추출 대상 신규 동영상이 없습니다.", None)
        return summary

    gemini_model = await settings_service.get_gemini_engine_version(session)
    resolved_llm = llm or poi_extraction.make_gemini_llm(model=gemini_model)
    resolved_transcript_fetcher = transcript_fetcher or _default_transcript_fetcher
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        owned_geocode_context = await _make_geocode_context(
            http_client,
            settings=settings,
            geocode_decider=geocode_decider,
            geocode_applier=geocode_applier,
        )

        await _report(
            status_reporter,
            f"동영상 {len(videos)}개의 자막·장소 추출을 시작합니다.",
            0.87,
        )

        for index, video in enumerate(videos, start=1):
            if video.crawl_status in {CrawlStatus.SUMMARIZED, CrawlStatus.GEOCODED, CrawlStatus.DONE}:
                summary["skipped_videos"] += 1
                continue

            video_label = video.title or video.video_id
            summary["processed_videos"] += 1
            progress = 0.87 + (0.02 * index / max(1, len(videos)))
            try:
                await _report(
                    status_reporter,
                    f"Youtube 동영상 {video_label}의 자막을 추출 중입니다.",
                    progress,
                )
                existing_candidate_ids = await _candidate_ids_for_video(session, video.video_id)
                transcript = await resolved_transcript_fetcher(video.video_id)
                result = await summarize_service.summarize_video(
                    session,
                    resolved_store,
                    video=video,
                    transcript=transcript,
                    llm=resolved_llm,
                    gemini_model=gemini_model,
                    max_retries=max_retries,
                    status_reporter=status_reporter,
                )
                if result.get("status") != "summarized":
                    summary["failed_videos"] += 1
                    continue

                summary["summarized_videos"] += 1
                new_candidates = await _new_candidates_for_video(
                    session,
                    video.video_id,
                    existing_candidate_ids,
                )
                summary["created_candidates"] += len(new_candidates)
                geocoded_any = await _apply_geocoding(
                    session,
                    new_candidates,
                    context=owned_geocode_context,
                    summary=summary,
                    status_reporter=status_reporter,
                )
                if geocoded_any:
                    refreshed_video = await session.get(YoutubeVideo, video.video_id)
                    if refreshed_video is not None:
                        refreshed_video.crawl_status = CrawlStatus.GEOCODED
                        await session.commit()
            except Exception as exc:
                summary["failed_videos"] += 1
                await _report(
                    status_reporter,
                    f"{video_label}의 장소 추출 후처리에 실패했습니다: {exc}",
                    None,
                )

        await _report(
            status_reporter,
            "장소 추출 후처리를 완료했습니다. "
            f"후보 {summary['created_candidates']}개, "
            f"확정 장소 {summary['matched_places']}개, "
            f"검수 필요 {summary['needs_review_candidates']}개입니다.",
            0.89,
        )
        return summary


async def _apply_geocoding(
    session: AsyncSession,
    candidates: Sequence[ExtractedPlaceCandidate],
    *,
    context: "_GeocodeContext",
    summary: dict[str, Any],
    status_reporter: StatusReporter | None,
) -> bool:
    geocoded_any = False
    for candidate in candidates:
        if context.decider is None:
            summary["needs_review_candidates"] += 1
            await _report(
                status_reporter,
                f"{candidate.ai_place_name}의 지오코딩 공급자 키가 없어 검수 큐에 남겼습니다.",
                None,
            )
            continue

        query = _candidate_query(candidate)
        await _report(status_reporter, f"{candidate.ai_place_name}의 위치를 보정 중입니다.", None)
        decision = await context.decider(candidate)
        place = await context.applier(session, candidate, decision)
        if place is None:
            summary["needs_review_candidates"] += 1
            await _report(
                status_reporter,
                f"{candidate.ai_place_name}의 위치를 자동 확정하지 못해 검수 큐에 남겼습니다.",
                None,
            )
            continue

        geocoded_any = True
        summary["matched_places"] += 1
        await _report(
            status_reporter,
            f"{candidate.ai_place_name}를 장소 목록에 확정했습니다. 검색어는 \"{query}\" 입니다.",
            None,
        )
    return geocoded_any


async def _load_target_videos(
    session: AsyncSession,
    *,
    video_ids: Sequence[str] | None,
    limit: int | None,
) -> list[YoutubeVideo]:
    stmt = select(YoutubeVideo).where(YoutubeVideo.crawl_status != CrawlStatus.DONE)
    if video_ids:
        stmt = stmt.where(YoutubeVideo.video_id.in_(list(video_ids)))
    stmt = stmt.order_by(YoutubeVideo.crawled_at.desc())
    if limit is not None:
        stmt = stmt.limit(max(1, limit))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _candidate_ids_for_video(session: AsyncSession, video_id: str) -> set[int]:
    result = await session.execute(
        select(ExtractedPlaceCandidate.id).where(
            ExtractedPlaceCandidate.video_id == video_id
        )
    )
    return {int(value) for value in result.scalars().all()}


async def _new_candidates_for_video(
    session: AsyncSession,
    video_id: str,
    existing_ids: set[int],
) -> list[ExtractedPlaceCandidate]:
    stmt = select(ExtractedPlaceCandidate).where(
        ExtractedPlaceCandidate.video_id == video_id
    )
    if existing_ids:
        stmt = stmt.where(ExtractedPlaceCandidate.id.not_in(existing_ids))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _default_transcript_fetcher(video_id: str) -> TranscriptResult | None:
    return await get_transcript_async(video_id)


def _make_media_store(settings: Settings) -> media_store.MediaStore:
    if (
        settings.RUSTFS_ENABLED
        and _configured_secret(settings.RUSTFS_ACCESS_KEY)
        and _configured_secret(settings.RUSTFS_SECRET_KEY)
    ):
        return media_store.RustFSMediaStore()
    return media_store.InMemoryMediaStore(endpoint="memory://rustfs-unconfigured")


def _storage_mode(store: media_store.MediaStore) -> str:
    if isinstance(store, media_store.InMemoryMediaStore):
        return "memory"
    return "rustfs"


class _GeocodeContext:
    def __init__(
        self,
        decider: GeocodeDecider | None,
        applier: GeocodeApplier,
    ) -> None:
        self.decider = decider
        self.applier = applier


async def _make_geocode_context(
    http_client: httpx.AsyncClient,
    *,
    settings: Settings,
    geocode_decider: GeocodeDecider | None,
    geocode_applier: GeocodeApplier | None,
) -> _GeocodeContext:
    if geocode_decider is not None:
        return _GeocodeContext(
            geocode_decider,
            geocode_applier or _default_geocode_applier(None),
        )

    vworld_client = (
        AsyncVworldClient(api_key=settings.VWORLD_SERVICE_KEY)
        if _configured_secret(settings.VWORLD_SERVICE_KEY)
        else None
    )
    kakao = (
        KakaoGeocoder(settings.KAKAO_REST_API_KEY, http_client)
        if _configured_secret(settings.KAKAO_REST_API_KEY)
        else None
    )
    naver = (
        NaverGeocoder(settings.NAVER_CLIENT_ID, settings.NAVER_CLIENT_SECRET, http_client)
        if _configured_secret(settings.NAVER_CLIENT_ID)
        and _configured_secret(settings.NAVER_CLIENT_SECRET)
        else None
    )

    if vworld_client is None and kakao is None and naver is None:
        return _GeocodeContext(None, geocode_applier or _default_geocode_applier(None))

    async def default_decider(candidate: ExtractedPlaceCandidate) -> GeocodeDecision:
        return await geocode_service.geocode_query(
            _candidate_query(candidate),
            vworld=vworld_client,
            kakao=kakao,
            naver=naver,
        )

    return _GeocodeContext(
        default_decider,
        geocode_applier or _default_geocode_applier(vworld_client),
    )


def _default_geocode_applier(vworld_client: AsyncVworldClient | None) -> GeocodeApplier:
    async def apply(
        session: AsyncSession,
        candidate: ExtractedPlaceCandidate,
        decision: GeocodeDecision,
    ) -> TravelPlace | None:
        return await geocode_service.apply_geocode_to_candidate(
            session,
            candidate,
            decision,
            vworld=vworld_client,
        )

    return apply


def _candidate_query(candidate: ExtractedPlaceCandidate) -> str:
    parts = [candidate.location_hint, candidate.ai_place_name]
    return " ".join(part.strip() for part in parts if part and part.strip())


def _configured_secret(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.strip().casefold()
    return not lowered.startswith("your_") and "placeholder" not in lowered


async def _report(
    status_reporter: StatusReporter | None,
    message: str,
    progress: float | None = None,
) -> None:
    if status_reporter is not None:
        await status_reporter(message, progress)

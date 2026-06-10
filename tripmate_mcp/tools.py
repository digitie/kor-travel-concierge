"""MCP 읽기/쓰기 도구 runtime.

도구 함수는 FastMCP 등록과 단위 테스트에서 같은 경로를 사용한다. 쓰기 도구는
Pydantic 입력 검증, 멱등 키, 감사 로그를 반드시 거친다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MediaAsset, RunSource
from app.services import audit_service, crawl_run_service, place_service


READ_TOOLS: list[dict[str, str]] = [
    {
        "name": "get_harvest_status",
        "summary": "수집 작업 상태·진행률·실패 원인·완료 요약 조회",
    },
    {
        "name": "search_existing_places",
        "summary": "적재된 장소를 검색어·반경·카테고리로 검색",
    },
    {
        "name": "get_place_detail",
        "summary": "장소 상세·원본 영상·대표 프레임·위치 보정 근거 조회",
    },
]

WRITE_TOOLS: list[dict[str, str]] = [
    {
        "name": "harvest_travel_destinations",
        "summary": "검색어·채널·재생목록 기준 수집 작업 생성 후 job_id 반환",
    },
    {
        "name": "correct_place",
        "summary": "장소명·주소·좌표·카테고리·설명 보정",
    },
    {
        "name": "merge_places",
        "summary": "중복 장소 병합",
    },
    {
        "name": "trigger_deep_research",
        "summary": "Gemini Deep Research 작업 트리거",
    },
    {
        "name": "review_unmatched_place",
        "summary": "needs_review 후보 검수 메타데이터 기록",
    },
    {
        "name": "resolve_place_candidate",
        "summary": "후보를 확정 장소와 매칭하거나 제외 처리",
    },
]


class StrictModel(BaseModel):
    """MCP 입력 모델 공통 설정."""

    model_config = ConfigDict(extra="forbid")


class HarvestTravelDestinationsInput(StrictModel):
    idempotency_key: str = Field(min_length=8)
    query: str | None = Field(default=None, min_length=1)
    channel_id: str | None = Field(default=None, min_length=1)
    playlist_id: str | None = Field(default=None, min_length=1)
    max_videos: int = Field(default=20, ge=1, le=50)

    @model_validator(mode="after")
    def validate_single_target(self) -> "HarvestTravelDestinationsInput":
        targets = [self.query, self.channel_id, self.playlist_id]
        if sum(1 for value in targets if value) != 1:
            raise ValueError("query, channel_id, playlist_id 중 정확히 하나가 필요하다")
        return self


class HarvestStatusInput(StrictModel):
    job_id: int = Field(gt=0)


class SearchExistingPlacesInput(StrictModel):
    query: str | None = Field(default=None, min_length=1)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_meters: float | None = Field(default=None, gt=0, le=200_000)
    category: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_radius(self) -> "SearchExistingPlacesInput":
        has_any_geo = any(
            value is not None
            for value in (self.latitude, self.longitude, self.radius_meters)
        )
        has_all_geo = all(
            value is not None
            for value in (self.latitude, self.longitude, self.radius_meters)
        )
        if has_any_geo and not has_all_geo:
            raise ValueError("반경 검색에는 latitude, longitude, radius_meters가 모두 필요하다")
        return self


class PlaceDetailInput(StrictModel):
    place_id: int = Field(gt=0)


class CorrectPlaceInput(StrictModel):
    idempotency_key: str = Field(min_length=8)
    place_id: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    gemini_enriched_description: str | None = None
    description_review_status: Literal[
        "ai_generated", "user_reviewed", "rejected"
    ] | None = None
    official_address: str | None = None
    road_address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    api_source: str | None = None
    category: str | None = None
    is_geocoded: bool | None = None

    @model_validator(mode="after")
    def validate_updates(self) -> "CorrectPlaceInput":
        if (self.latitude is None) ^ (self.longitude is None):
            raise ValueError("좌표 보정은 latitude와 longitude를 함께 제공해야 한다")
        if not _non_none_update_fields(self, exclude={"idempotency_key", "place_id"}):
            raise ValueError("보정할 필드가 최소 1개 필요하다")
        return self


class MergePlacesInput(StrictModel):
    idempotency_key: str = Field(min_length=8)
    source_place_id: int = Field(gt=0)
    target_place_id: int = Field(gt=0)
    review_note: str | None = None

    @model_validator(mode="after")
    def validate_distinct_places(self) -> "MergePlacesInput":
        if self.source_place_id == self.target_place_id:
            raise ValueError("source_place_id와 target_place_id는 달라야 한다")
        return self


class TriggerDeepResearchInput(StrictModel):
    idempotency_key: str = Field(min_length=8)
    place_id: int = Field(gt=0)
    prompt: str | None = None
    max_sources: int = Field(default=8, ge=1, le=20)


class ReviewUnmatchedPlaceInput(StrictModel):
    idempotency_key: str = Field(min_length=8)
    candidate_id: int = Field(gt=0)
    reviewed_by: str = Field(default="mcp", min_length=1)
    review_note: str | None = None


class ResolvePlaceCandidateInput(StrictModel):
    idempotency_key: str = Field(min_length=8)
    candidate_id: int = Field(gt=0)
    action: Literal["match_existing", "create_place", "ignore"]
    reviewed_by: str = Field(default="mcp", min_length=1)
    review_note: str | None = None
    place_id: int | None = Field(default=None, gt=0)
    corrected_name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    gemini_enriched_description: str | None = None
    official_address: str | None = None
    road_address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    api_source: str | None = None
    category: str | None = None

    @model_validator(mode="after")
    def validate_action_payload(self) -> "ResolvePlaceCandidateInput":
        if self.action == "match_existing" and self.place_id is None:
            raise ValueError("match_existing에는 place_id가 필요하다")
        if self.action == "create_place":
            missing = [
                key
                for key, value in (
                    ("corrected_name", self.corrected_name),
                    ("latitude", self.latitude),
                    ("longitude", self.longitude),
                )
                if value is None
            ]
            if missing:
                raise ValueError(f"create_place에는 {', '.join(missing)} 값이 필요하다")
        return self


def _non_none_update_fields(model: BaseModel, *, exclude: set[str]) -> dict[str, Any]:
    data = model.model_dump()
    return {key: value for key, value in data.items() if key not in exclude and value is not None}


SessionFactory = Callable[[], Any]


@dataclass(slots=True)
class ToolRuntime:
    """MCP 도구 실행 runtime."""

    session_factory: SessionFactory
    write_enabled: bool = True

    async def harvest_travel_destinations(self, **kwargs: Any) -> dict[str, Any]:
        payload = HarvestTravelDestinationsInput.model_validate(kwargs)
        self._ensure_write_enabled()
        action = "harvest.create"
        request = payload.model_dump(exclude_none=True)
        async with self.session_factory() as session:
            cached = await self._idempotent_result(
                session, action, payload.idempotency_key, request=request
            )
            if cached is not None:
                return cached

            if payload.channel_id:
                target_type, target_id = "channel", payload.channel_id
            elif payload.playlist_id:
                target_type, target_id = "playlist", payload.playlist_id
            else:
                target_type, target_id = "keyword", payload.query

            run = await crawl_run_service.create_run(
                session,
                job_type="harvest",
                source=RunSource.MCP,
                target_type=target_type,
                target_id=target_id,
                payload=payload.model_dump(),
                commit=False,
            )
            result = {
                "job_id": str(run.id),
                "state": run.state,
                "target_type": target_type,
                "target_id": target_id,
                "idempotent": False,
            }
            await self._record_write(
                session,
                action=action,
                idempotency_key=payload.idempotency_key,
                target_type="crawl_run",
                target_id=str(run.id),
                request=request,
                result=result,
            )
            return result

    async def get_harvest_status(self, **kwargs: Any) -> dict[str, Any]:
        payload = HarvestStatusInput.model_validate(kwargs)
        async with self.session_factory() as session:
            run = await crawl_run_service.get_run(session, payload.job_id)
            if run is None:
                raise ValueError(f"job not found: {payload.job_id}")
            return _serialize_run(run)

    async def search_existing_places(self, **kwargs: Any) -> dict[str, Any]:
        payload = SearchExistingPlacesInput.model_validate(kwargs)
        async with self.session_factory() as session:
            results = await place_service.search_places(
                session,
                query=payload.query,
                lat=payload.latitude,
                lng=payload.longitude,
                radius_meters=payload.radius_meters,
                category=payload.category,
                limit=payload.limit,
            )
            return {
                "places": [
                    {
                        **_serialize_place(place),
                        "distance_meters": round(distance, 2)
                        if distance is not None
                        else None,
                    }
                    for place, distance in results
                ]
            }

    async def get_place_detail(self, **kwargs: Any) -> dict[str, Any]:
        payload = PlaceDetailInput.model_validate(kwargs)
        async with self.session_factory() as session:
            place = await place_service.get_place(session, payload.place_id)
            if place is None:
                raise ValueError(f"place not found: {payload.place_id}")

            mappings = await place_service.get_place_video_mappings(
                session, place_id=payload.place_id
            )
            videos = await place_service.get_videos_by_ids(
                session, [mapping.video_id for mapping in mappings]
            )
            candidates = await place_service.list_candidates_for_place(
                session, place_id=payload.place_id
            )
            frame_assets = await _load_frame_assets(
                session,
                [
                    mapping.frame_asset_id
                    for mapping in mappings
                    if mapping.frame_asset_id is not None
                ],
            )
            source_channel_ids = {
                video.channel_id for video in videos.values() if video.channel_id
            }
            return {
                "place": _serialize_place(place),
                "mention_count": len(mappings),
                "source_channel_count": len(source_channel_ids),
                "video_mappings": [
                    _serialize_mapping(mapping, videos.get(mapping.video_id), frame_assets)
                    for mapping in mappings
                ],
                "matched_candidates": [_serialize_candidate(candidate) for candidate in candidates],
            }

    async def correct_place(self, **kwargs: Any) -> dict[str, Any]:
        payload = CorrectPlaceInput.model_validate(kwargs)
        self._ensure_write_enabled()
        action = "place.correct"
        request = payload.model_dump(exclude_none=True)
        async with self.session_factory() as session:
            cached = await self._idempotent_result(
                session, action, payload.idempotency_key, request=request
            )
            if cached is not None:
                return cached
            updates = _non_none_update_fields(payload, exclude={"idempotency_key", "place_id"})
            place = await place_service.correct_place(
                session, place_id=payload.place_id, updates=updates, commit=False
            )
            result = {"place": _serialize_place(place), "idempotent": False}
            await self._record_write(
                session,
                action=action,
                idempotency_key=payload.idempotency_key,
                target_type="travel_place",
                target_id=str(place.place_id),
                request=request,
                result=result,
            )
            return result

    async def merge_places(self, **kwargs: Any) -> dict[str, Any]:
        payload = MergePlacesInput.model_validate(kwargs)
        self._ensure_write_enabled()
        action = "place.merge"
        request = payload.model_dump(exclude_none=True)
        async with self.session_factory() as session:
            cached = await self._idempotent_result(
                session, action, payload.idempotency_key, request=request
            )
            if cached is not None:
                return cached
            target = await place_service.merge_places(
                session,
                source_place_id=payload.source_place_id,
                target_place_id=payload.target_place_id,
                commit=False,
            )
            result = {
                "target_place": _serialize_place(target),
                "merged_source_place_id": payload.source_place_id,
                "idempotent": False,
            }
            await self._record_write(
                session,
                action=action,
                idempotency_key=payload.idempotency_key,
                target_type="travel_place",
                target_id=str(payload.target_place_id),
                request=request,
                result=result,
            )
            return result

    async def trigger_deep_research(self, **kwargs: Any) -> dict[str, Any]:
        payload = TriggerDeepResearchInput.model_validate(kwargs)
        self._ensure_write_enabled()
        action = "deep_research.create"
        request = payload.model_dump(exclude_none=True)
        async with self.session_factory() as session:
            cached = await self._idempotent_result(
                session, action, payload.idempotency_key, request=request
            )
            if cached is not None:
                return cached
            place = await place_service.get_place(session, payload.place_id)
            if place is None:
                raise ValueError(f"place not found: {payload.place_id}")
            run = await crawl_run_service.create_run(
                session,
                job_type="deep_research",
                source=RunSource.MCP,
                target_type="place",
                target_id=str(payload.place_id),
                payload=payload.model_dump(),
                commit=False,
            )
            result = {
                "job_id": str(run.id),
                "state": run.state,
                "place_id": payload.place_id,
                "idempotent": False,
            }
            await self._record_write(
                session,
                action=action,
                idempotency_key=payload.idempotency_key,
                target_type="crawl_run",
                target_id=str(run.id),
                request=request,
                result=result,
            )
            return result

    async def review_unmatched_place(self, **kwargs: Any) -> dict[str, Any]:
        payload = ReviewUnmatchedPlaceInput.model_validate(kwargs)
        self._ensure_write_enabled()
        action = "candidate.review"
        request = payload.model_dump(exclude_none=True)
        async with self.session_factory() as session:
            cached = await self._idempotent_result(
                session, action, payload.idempotency_key, request=request
            )
            if cached is not None:
                return cached
            candidate = await place_service.review_candidate(
                session,
                candidate_id=payload.candidate_id,
                reviewed_by=payload.reviewed_by,
                review_note=payload.review_note,
                commit=False,
            )
            result = {"candidate": _serialize_candidate(candidate), "idempotent": False}
            await self._record_write(
                session,
                action=action,
                idempotency_key=payload.idempotency_key,
                target_type="extracted_place_candidate",
                target_id=str(payload.candidate_id),
                request=request,
                result=result,
            )
            return result

    async def resolve_place_candidate(self, **kwargs: Any) -> dict[str, Any]:
        payload = ResolvePlaceCandidateInput.model_validate(kwargs)
        self._ensure_write_enabled()
        action = "candidate.resolve"
        request = payload.model_dump(exclude_none=True)
        async with self.session_factory() as session:
            cached = await self._idempotent_result(
                session, action, payload.idempotency_key, request=request
            )
            if cached is not None:
                return cached
            place_data = None
            if payload.action == "create_place":
                place_data = {
                    "name": payload.corrected_name,
                    "description": payload.description,
                    "gemini_enriched_description": payload.gemini_enriched_description,
                    "official_address": payload.official_address,
                    "road_address": payload.road_address,
                    "latitude": payload.latitude,
                    "longitude": payload.longitude,
                    "api_source": payload.api_source,
                    "category": payload.category,
                }
            candidate, place, mapping = await place_service.resolve_candidate(
                session,
                candidate_id=payload.candidate_id,
                action=payload.action,
                reviewed_by=payload.reviewed_by,
                review_note=payload.review_note,
                place_id=payload.place_id,
                place_data=place_data,
                commit=False,
            )
            result = {
                "candidate": _serialize_candidate(candidate),
                "place": _serialize_place(place) if place else None,
                "mapping": _serialize_mapping(mapping, None, {}) if mapping else None,
                "idempotent": False,
            }
            await self._record_write(
                session,
                action=action,
                idempotency_key=payload.idempotency_key,
                target_type="extracted_place_candidate",
                target_id=str(payload.candidate_id),
                request=request,
                result=result,
            )
            return result

    def _ensure_write_enabled(self) -> None:
        if not self.write_enabled:
            raise PermissionError("MCP 쓰기 도구가 비활성화되어 있다")

    async def _idempotent_result(
        self,
        session: AsyncSession,
        action: str,
        idempotency_key: str,
        *,
        request: dict[str, Any],
    ) -> dict[str, Any] | None:
        log = await audit_service.find_by_idempotency_key(
            session,
            actor_type="mcp",
            action=action,
            idempotency_key=idempotency_key,
        )
        if log is None or not log.payload_json:
            return None
        payload = json.loads(log.payload_json)
        previous_request = payload.get("request") or {}
        if previous_request != request:
            raise ValueError("같은 idempotency_key로 다른 요청 파라미터를 사용할 수 없다")
        result = dict(payload.get("result") or {})
        result["idempotent"] = True
        result["audit_log_id"] = log.id
        return result

    async def _record_write(
        self,
        session: AsyncSession,
        *,
        action: str,
        idempotency_key: str,
        target_type: str,
        target_id: str,
        request: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        await audit_service.record(
            session,
            actor_type="mcp",
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload={
                "idempotency_key": idempotency_key,
                "request": request,
                "result": result,
            },
        )


def register_mcp_tools(server: Any, runtime: ToolRuntime) -> None:
    """FastMCP 서버에 도구를 등록한다."""

    @server.tool(
        name="get_harvest_status",
        description="수집 작업 상태, 진행률, 실패 원인, 완료 요약을 반환한다.",
    )
    async def get_harvest_status(job_id: int) -> dict[str, Any]:
        return await runtime.get_harvest_status(job_id=job_id)

    @server.tool(
        name="search_existing_places",
        description="확정 장소를 검색어, 카테고리, 좌표 반경 조건으로 조회한다.",
    )
    async def search_existing_places(
        query: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_meters: float | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return await runtime.search_existing_places(
            query=query,
            latitude=latitude,
            longitude=longitude,
            radius_meters=radius_meters,
            category=category,
            limit=limit,
        )

    @server.tool(
        name="get_place_detail",
        description="장소 상세, 연결 영상, 대표 프레임, 매칭 후보 근거를 반환한다.",
    )
    async def get_place_detail(place_id: int) -> dict[str, Any]:
        return await runtime.get_place_detail(place_id=place_id)

    if not runtime.write_enabled:
        return

    @server.tool(
        name="harvest_travel_destinations",
        description="검색어, 채널, 재생목록 중 하나로 harvest 작업을 생성한다.",
    )
    async def harvest_travel_destinations(
        idempotency_key: str,
        query: str | None = None,
        channel_id: str | None = None,
        playlist_id: str | None = None,
        max_videos: int = 20,
    ) -> dict[str, Any]:
        return await runtime.harvest_travel_destinations(
            idempotency_key=idempotency_key,
            query=query,
            channel_id=channel_id,
            playlist_id=playlist_id,
            max_videos=max_videos,
        )

    @server.tool(name="correct_place", description="확정 장소 정보를 수동 보정한다.")
    async def correct_place(
        idempotency_key: str,
        place_id: int,
        name: str | None = None,
        description: str | None = None,
        gemini_enriched_description: str | None = None,
        description_review_status: str | None = None,
        official_address: str | None = None,
        road_address: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        api_source: str | None = None,
        category: str | None = None,
        is_geocoded: bool | None = None,
    ) -> dict[str, Any]:
        return await runtime.correct_place(
            idempotency_key=idempotency_key,
            place_id=place_id,
            name=name,
            description=description,
            gemini_enriched_description=gemini_enriched_description,
            description_review_status=description_review_status,
            official_address=official_address,
            road_address=road_address,
            latitude=latitude,
            longitude=longitude,
            api_source=api_source,
            category=category,
            is_geocoded=is_geocoded,
        )

    @server.tool(name="merge_places", description="중복 장소를 하나의 확정 장소로 병합한다.")
    async def merge_places(
        idempotency_key: str,
        source_place_id: int,
        target_place_id: int,
        review_note: str | None = None,
    ) -> dict[str, Any]:
        return await runtime.merge_places(
            idempotency_key=idempotency_key,
            source_place_id=source_place_id,
            target_place_id=target_place_id,
            review_note=review_note,
        )

    @server.tool(
        name="trigger_deep_research",
        description="장소 기준 Gemini Deep Research 작업을 생성한다.",
    )
    async def trigger_deep_research(
        idempotency_key: str,
        place_id: int,
        prompt: str | None = None,
        max_sources: int = 8,
    ) -> dict[str, Any]:
        return await runtime.trigger_deep_research(
            idempotency_key=idempotency_key,
            place_id=place_id,
            prompt=prompt,
            max_sources=max_sources,
        )

    @server.tool(
        name="review_unmatched_place",
        description="needs_review 후보에 검수자와 검수 메모를 기록한다.",
    )
    async def review_unmatched_place(
        idempotency_key: str,
        candidate_id: int,
        reviewed_by: str = "mcp",
        review_note: str | None = None,
    ) -> dict[str, Any]:
        return await runtime.review_unmatched_place(
            idempotency_key=idempotency_key,
            candidate_id=candidate_id,
            reviewed_by=reviewed_by,
            review_note=review_note,
        )

    @server.tool(
        name="resolve_place_candidate",
        description="후보를 기존 장소와 매칭하거나 신규 장소로 만들거나 제외한다.",
    )
    async def resolve_place_candidate(
        idempotency_key: str,
        candidate_id: int,
        action: Literal["match_existing", "create_place", "ignore"],
        reviewed_by: str = "mcp",
        review_note: str | None = None,
        place_id: int | None = None,
        corrected_name: str | None = None,
        description: str | None = None,
        gemini_enriched_description: str | None = None,
        official_address: str | None = None,
        road_address: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        api_source: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        return await runtime.resolve_place_candidate(
            idempotency_key=idempotency_key,
            candidate_id=candidate_id,
            action=action,
            reviewed_by=reviewed_by,
            review_note=review_note,
            place_id=place_id,
            corrected_name=corrected_name,
            description=description,
            gemini_enriched_description=gemini_enriched_description,
            official_address=official_address,
            road_address=road_address,
            latitude=latitude,
            longitude=longitude,
            api_source=api_source,
            category=category,
        )


def tool_metadata(*, write_enabled: bool) -> list[dict[str, str]]:
    """현재 설정에서 등록될 도구 metadata를 반환한다."""
    tools = list(READ_TOOLS)
    if write_enabled:
        tools += list(WRITE_TOOLS)
    return tools


async def _load_frame_assets(
    session: AsyncSession, frame_asset_ids: list[int]
) -> dict[int, MediaAsset]:
    if not frame_asset_ids:
        return {}
    stmt = select(MediaAsset).where(MediaAsset.id.in_(frame_asset_ids))
    result = await session.execute(stmt)
    return {asset.id: asset for asset in result.scalars().all()}


def _serialize_run(run: Any) -> dict[str, Any]:
    return {
        "job_id": str(run.id),
        "job_type": run.job_type,
        "source": run.source,
        "target_type": run.target_type,
        "target_id": run.target_id,
        "state": run.state,
        "progress": run.progress,
        "current_message": run.current_message,
        "status_logs": crawl_run_service.load_status_logs(run),
        "retry_count": run.retry_count,
        "last_error": run.last_error,
        "payload": _json_or_none(run.payload_json),
        "result": _json_or_none(run.result_json),
        "started_at": _iso(run.started_at),
        "heartbeat_at": _iso(run.heartbeat_at),
        "finished_at": _iso(run.finished_at),
        "created_at": _iso(run.created_at),
    }


def _serialize_place(place: Any) -> dict[str, Any]:
    return {
        "place_id": place.place_id,
        "name": place.name,
        "description": place.description,
        "gemini_enriched_description": place.gemini_enriched_description,
        "description_review_status": place.description_review_status,
        "official_address": place.official_address,
        "road_address": place.road_address,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "api_source": place.api_source,
        "category": place.category,
        "is_geocoded": place.is_geocoded,
        "detailed_research_content": place.detailed_research_content,
        "last_reviewed_at": _iso(place.last_reviewed_at),
        "created_at": _iso(place.created_at),
    }


def _serialize_candidate(candidate: Any) -> dict[str, Any]:
    return {
        "candidate_id": candidate.id,
        "video_id": candidate.video_id,
        "source_channel_id": candidate.source_channel_id,
        "source_playlist_id": candidate.source_playlist_id,
        "analysis_run_id": candidate.analysis_run_id,
        "source_kind": candidate.source_kind,
        "source_text": candidate.source_text,
        "ai_place_name": candidate.ai_place_name,
        "speaker_note": candidate.speaker_note,
        "location_hint": candidate.location_hint,
        "timestamp_start": candidate.timestamp_start,
        "timestamp_end": candidate.timestamp_end,
        "candidate_category": candidate.candidate_category,
        "match_status": candidate.match_status,
        "matched_place_id": candidate.matched_place_id,
        "confidence_score": candidate.confidence_score,
        "provider_evidence_json": candidate.provider_evidence_json,
        "feature_export_status": candidate.feature_export_status,
        "reviewed_by": candidate.reviewed_by,
        "reviewed_at": _iso(candidate.reviewed_at),
        "review_note": candidate.review_note,
        "created_at": _iso(candidate.created_at),
    }


def _serialize_mapping(
    mapping: Any,
    video: Any | None,
    frame_assets: dict[int, MediaAsset],
) -> dict[str, Any]:
    frame_asset = (
        frame_assets.get(mapping.frame_asset_id)
        if mapping and mapping.frame_asset_id is not None
        else None
    )
    return {
        "mapping_id": mapping.id,
        "video_id": mapping.video_id,
        "place_id": mapping.place_id,
        "place_candidate_id": mapping.place_candidate_id,
        "source_channel_id": mapping.source_channel_id,
        "source_playlist_id": mapping.source_playlist_id,
        "analysis_run_id": mapping.analysis_run_id,
        "source_kind": mapping.source_kind,
        "ai_summary": mapping.ai_summary,
        "speaker_note": mapping.speaker_note,
        "timestamp_start": mapping.timestamp_start,
        "timestamp_end": mapping.timestamp_end,
        "provider_evidence_json": mapping.provider_evidence_json,
        "feature_export_status": mapping.feature_export_status,
        "frame_asset": _serialize_media_asset(frame_asset) if frame_asset else None,
        "video": _serialize_video(video) if video else None,
        "created_at": _iso(mapping.created_at),
    }


def _serialize_video(video: Any) -> dict[str, Any]:
    return {
        "video_id": video.video_id,
        "title": video.title,
        "url": video.url,
        "channel_id": video.channel_id,
        "channel_name": video.channel_name,
        "published_at": _iso(video.published_at),
        "view_count": video.view_count,
        "like_count": video.like_count,
        "engagement_score": video.engagement_score,
        "description_raw": video.description_raw,
        "description_gemini_corrected": video.description_gemini_corrected,
        "description_gemini_corrected_at": _iso(video.description_gemini_corrected_at),
        "description_gemini_model": video.description_gemini_model,
        "crawl_status": video.crawl_status,
        "crawled_at": _iso(video.crawled_at),
    }


def _serialize_media_asset(asset: Any) -> dict[str, Any]:
    return {
        "id": asset.id,
        "asset_type": asset.asset_type,
        "video_id": asset.video_id,
        "place_id": asset.place_id,
        "storage_provider": asset.storage_provider,
        "bucket": asset.bucket,
        "object_key": asset.object_key,
        "object_uri": asset.object_uri,
        "content_type": asset.content_type,
        "size_bytes": asset.size_bytes,
        "sha256": asset.sha256,
        "retention_policy": asset.retention_policy,
        "created_at": _iso(asset.created_at),
    }


def _json_or_none(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    return json.loads(value)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


__all__ = [
    "READ_TOOLS",
    "WRITE_TOOLS",
    "ToolRuntime",
    "register_mcp_tools",
    "tool_metadata",
]

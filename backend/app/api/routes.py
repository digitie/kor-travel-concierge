"""Web REST API 라우터.

`docs/architecture.md` 3.1의 웹 UX 계약을 노출한다. 장시간 작업은 직접 수행하지
않고 `crawl_runs` 작업만 생성한 뒤 `job_id`를 즉시 반환한다(ADR-13).
실제 ETL 실행은 scheduler 단일 실행자가 담당한다.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.models import MediaAsset, RunSource
from app.services import (
    audit_service,
    crawl_run_service,
    place_service,
    settings_service,
)

router = APIRouter(prefix="/api")


class HarvestRequest(BaseModel):
    """수집 시작 요청 본문."""

    query: str | None = None
    channel_id: str | None = None
    playlist_id: str | None = None
    max_videos: int = 20


class HarvestJob(BaseModel):
    """수집 작업 식별자 응답."""

    job_id: str
    state: str


class HarvestStatus(BaseModel):
    """수집 작업 상태 응답."""

    job_id: str
    state: str
    progress: float
    last_error: str | None = None
    result: dict[str, Any] | None = None


class CorrectPlaceRequest(BaseModel):
    """장소 수동 보정 요청."""

    name: str | None = None
    description: str | None = None
    gemini_enriched_description: str | None = None
    official_address: str | None = None
    road_address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    category: str | None = None
    api_source: str | None = None


class ResolveCandidateRequest(BaseModel):
    """매칭 실패 후보 해결 요청."""

    action: str = Field(pattern="^(match_existing|create_place|ignore)$")
    place_id: int | None = None
    corrected_name: str | None = None
    description: str | None = None
    gemini_enriched_description: str | None = None
    official_address: str | None = None
    road_address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    category: str | None = None
    api_source: str | None = "manual"
    reviewed_by: str = "web"
    review_note: str | None = None


class DeepResearchRequest(BaseModel):
    """Deep Research 작업 생성 요청."""

    prompt: str | None = None
    max_sources: int = Field(default=8, ge=1, le=20)


# --- 수집 작업 (crawl_runs) ---


@router.post("/harvest", response_model=HarvestJob)
async def start_harvest(
    payload: HarvestRequest, session: AsyncSession = Depends(get_session)
) -> HarvestJob:
    """수집 작업을 `crawl_runs`에 생성하고 `job_id`를 반환한다.

    채널/재생목록/검색어 중 하나를 target으로 기록한다.
    """
    if payload.channel_id:
        target_type, target_id = "channel", payload.channel_id
    elif payload.playlist_id:
        target_type, target_id = "playlist", payload.playlist_id
    else:
        target_type, target_id = "keyword", payload.query

    run = await crawl_run_service.create_run(
        session,
        job_type="harvest",
        source=RunSource.WEB,
        target_type=target_type,
        target_id=target_id,
        payload=payload.model_dump(),
        commit=False,
    )
    await audit_service.record(
        session,
        actor_type="web",
        action="harvest.create",
        target_type="crawl_run",
        target_id=str(run.id),
        payload=payload.model_dump(),
    )
    return HarvestJob(job_id=str(run.id), state=run.state)


@router.get("/harvest/{job_id}", response_model=HarvestStatus)
async def get_harvest_status(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> HarvestStatus:
    """작업 상태·진행률·실패 원인·완료 요약을 반환한다."""
    run = await crawl_run_service.get_run(session, job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="job not found")
    return HarvestStatus(
        job_id=str(run.id),
        state=run.state,
        progress=run.progress,
        last_error=run.last_error,
        result=json.loads(run.result_json) if run.result_json else None,
    )


@router.get("/runs")
async def list_runs(
    state: str | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """최근 작업 목록을 반환한다."""
    runs = await crawl_run_service.list_runs(
        session, state=state, limit=max(1, min(limit, 100))
    )
    return [
        {
            "job_id": str(run.id),
            "job_type": run.job_type,
            "source": run.source,
            "target_type": run.target_type,
            "target_id": run.target_id,
            "state": run.state,
            "progress": run.progress,
            "retry_count": run.retry_count,
            "last_error": run.last_error,
            "result": json.loads(run.result_json) if run.result_json else None,
            "created_at": run.created_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }
        for run in runs
    ]


@router.get("/audit-logs")
async def list_audit_logs(
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """최근 감사 로그를 반환한다."""
    logs = await audit_service.list_recent(session, limit=max(1, min(limit, 100)))
    return [
        {
            "id": log.id,
            "actor_type": log.actor_type,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "payload": json.loads(log.payload_json) if log.payload_json else None,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


# --- 조회 ---


@router.get("/keywords")
async def list_keywords() -> list[dict[str, Any]]:
    # T-005/T-006에서 search_keywords 모델 기반으로 구현한다.
    return []


@router.get("/destinations")
async def list_destinations(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """확정 여행지 목록을 반환한다."""
    places = await place_service.list_places(session)
    return [
        {
            "place_id": p.place_id,
            "name": p.name,
            "description": p.description,
            "gemini_enriched_description": p.gemini_enriched_description,
            "latitude": p.latitude,
            "longitude": p.longitude,
            "category": p.category,
            "official_address": p.official_address,
            "road_address": p.road_address,
            "is_geocoded": p.is_geocoded,
        }
        for p in places
    ]


@router.get("/destinations/unmatched")
async def list_unmatched_candidates(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """매칭 실패(`needs_review`) 후보 검수 큐."""
    candidates = await place_service.list_unmatched_candidates(session)
    return [
        {
            "id": c.id,
            "video_id": c.video_id,
            "ai_place_name": c.ai_place_name,
            "location_hint": c.location_hint,
            "candidate_category": c.candidate_category,
            "match_status": c.match_status,
            "timestamp_start": c.timestamp_start,
        }
        for c in candidates
    ]


@router.post("/destinations/{place_id}/correct")
async def correct_destination(
    place_id: int,
    payload: CorrectPlaceRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """확정 장소를 수동 보정한다."""
    updates = payload.model_dump(exclude_none=True)
    if ("latitude" in updates) ^ ("longitude" in updates):
        raise HTTPException(status_code=400, detail="latitude/longitude required together")
    try:
        place = await place_service.correct_place(
            session,
            place_id=place_id,
            updates=updates,
            commit=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await audit_service.record(
        session,
        actor_type="web",
        action="place.correct",
        target_type="travel_place",
        target_id=str(place.place_id),
        payload=payload.model_dump(exclude_none=True),
    )
    return {"status": "updated", "place": _place_payload(place)}


@router.post("/destinations/{place_id}/deep-research")
async def trigger_deep_research(
    place_id: int,
    payload: DeepResearchRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """장소 기준 Deep Research 작업을 생성한다."""
    place = await place_service.get_place(session, place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="place not found")
    run = await crawl_run_service.create_run(
        session,
        job_type="deep_research",
        source=RunSource.WEB,
        target_type="place",
        target_id=str(place_id),
        payload=payload.model_dump(),
        commit=False,
    )
    await audit_service.record(
        session,
        actor_type="web",
        action="deep_research.create",
        target_type="crawl_run",
        target_id=str(run.id),
        payload=payload.model_dump(),
    )
    return {"job_id": str(run.id), "state": run.state, "place_id": place_id}


@router.post("/destinations/unmatched/{candidate_id}/resolve")
async def resolve_unmatched_candidate(
    candidate_id: int,
    payload: ResolveCandidateRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """매칭 실패 후보를 기존 장소, 신규 장소, 제외 중 하나로 해결한다."""
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
            "category": payload.category,
            "api_source": payload.api_source,
        }
    try:
        candidate, place, mapping = await place_service.resolve_candidate(
            session,
            candidate_id=candidate_id,
            action=payload.action,
            reviewed_by=payload.reviewed_by,
            review_note=payload.review_note,
            place_id=payload.place_id,
            place_data=place_data,
            commit=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit_service.record(
        session,
        actor_type="web",
        action="candidate.resolve",
        target_type="extracted_place_candidate",
        target_id=str(candidate_id),
        payload=payload.model_dump(exclude_none=True),
    )
    return {
        "status": "resolved",
        "candidate": {
            "id": candidate.id,
            "match_status": candidate.match_status,
            "matched_place_id": candidate.matched_place_id,
        },
        "place": _place_payload(place) if place else None,
        "mapping_id": mapping.id if mapping else None,
    }


@router.get("/storage/rustfs")
async def get_rustfs_status(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """RustFS 연결 상태와 DB에 기록된 객체 메타데이터 요약을 반환한다."""
    settings = get_settings()
    result = await session.execute(
        select(
            MediaAsset.asset_type,
            func.count(MediaAsset.id),
            func.coalesce(func.sum(MediaAsset.size_bytes), 0),
        ).group_by(MediaAsset.asset_type)
    )
    assets = [
        {
            "asset_type": row[0],
            "count": int(row[1]),
            "size_bytes": int(row[2] or 0),
        }
        for row in result.all()
    ]

    health_url = f"{settings.RUSTFS_ENDPOINT.rstrip('/')}{settings.RUSTFS_HEALTH_PATH}"
    health = {"ok": False, "url": health_url, "status_code": None, "error": None}
    if settings.RUSTFS_ENABLED:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(health_url)
            health["status_code"] = response.status_code
            health["ok"] = 200 <= response.status_code < 300
        except Exception as exc:  # pragma: no cover - 네트워크 환경별 메시지 차이
            health["error"] = str(exc)

    return {
        "enabled": settings.RUSTFS_ENABLED,
        "endpoint": settings.RUSTFS_ENDPOINT,
        "console_url": settings.RUSTFS_CONSOLE_URL,
        "retention_policy": settings.MEDIA_RETENTION_POLICY,
        "health": health,
        "assets": assets,
    }


# --- 설정 ---


@router.get("/settings")
async def get_settings_endpoint(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await settings_service.get_all(session)


@router.post("/settings")
async def update_settings_endpoint(
    settings: dict[str, Any], session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    values = {key: str(value) for key, value in settings.items()}
    try:
        await settings_service.set_many(session, values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit_service.record(
        session,
        actor_type="web",
        action="settings.update",
        target_type="system_settings",
        payload=settings,
    )
    return {"status": "updated", "settings": await settings_service.get_all(session)}


def _place_payload(place) -> dict[str, Any]:
    return {
        "place_id": place.place_id,
        "name": place.name,
        "description": place.description,
        "gemini_enriched_description": place.gemini_enriched_description,
        "official_address": place.official_address,
        "road_address": place.road_address,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "category": place.category,
        "api_source": place.api_source,
        "is_geocoded": place.is_geocoded,
    }

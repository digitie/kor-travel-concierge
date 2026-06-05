"""Web REST API 라우터.

`docs/architecture.md` 3.1의 웹 UX 계약을 노출한다. 장시간 작업은 직접 수행하지
않고 `crawl_runs` 작업만 생성한 뒤 `job_id`를 즉시 반환한다(ADR-13).
실제 ETL 실행은 scheduler 단일 실행자가 담당한다.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import RunSource
from app.services import audit_service, crawl_run_service, settings_service

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


# --- 조회 ---


@router.get("/keywords")
async def list_keywords() -> list[dict[str, Any]]:
    # T-005/T-006에서 search_keywords 모델 기반으로 구현한다.
    return []


@router.get("/destinations")
async def list_destinations() -> list[dict[str, Any]]:
    # T-005에서 travel_places 모델 기반으로 구현한다.
    return []


@router.get("/destinations/unmatched")
async def list_unmatched_candidates() -> list[dict[str, Any]]:
    """매칭 실패(`needs_review`) 후보 검수 큐 (T-005/T-008에서 구현)."""
    return []


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
    for key, value in settings.items():
        await settings_service.set_setting(session, key, str(value))
    await audit_service.record(
        session,
        actor_type="web",
        action="settings.update",
        target_type="system_settings",
        payload=settings,
    )
    return {"status": "updated", "settings": await settings_service.get_all(session)}

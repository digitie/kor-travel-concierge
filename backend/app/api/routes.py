"""Web REST API 라우터 (스캐폴드).

`docs/architecture.md` 3.1의 웹 UX 계약을 그대로 노출한다. 장시간 작업은 직접
수행하지 않고 `crawl_runs` 작업만 생성한 뒤 `job_id`를 즉시 반환한다(T-004).
현재는 계약 형태만 고정한 placeholder 응답이다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

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
    state: str = "pending"


# --- 수집 작업 (crawl_runs) ---


@router.post("/harvest", response_model=HarvestJob)
async def start_harvest(_payload: HarvestRequest) -> HarvestJob:
    """수집 작업을 `crawl_runs`에 생성하고 `job_id`를 반환한다 (T-004에서 구현)."""
    return HarvestJob(job_id="pending-stub")


@router.get("/harvest/{job_id}")
async def get_harvest_status(job_id: str) -> dict[str, Any]:
    """작업 상태·진행률·실패 원인·완료 요약을 반환한다 (T-004에서 구현)."""
    return {"job_id": job_id, "state": "pending", "progress": 0.0}


# --- 조회 ---


@router.get("/keywords")
async def list_keywords() -> list[dict[str, Any]]:
    return []


@router.get("/destinations")
async def list_destinations() -> list[dict[str, Any]]:
    return []


@router.get("/destinations/unmatched")
async def list_unmatched_candidates() -> list[dict[str, Any]]:
    """매칭 실패(`needs_review`) 후보 검수 큐 (T-005/T-008에서 구현)."""
    return []


# --- 설정 ---


@router.get("/settings")
async def get_settings_endpoint() -> dict[str, Any]:
    return {"gemini_engine_version": "gemini-2.0-flash"}


@router.post("/settings")
async def update_settings_endpoint(settings: dict[str, Any]) -> dict[str, Any]:
    return {"status": "updated", "settings": settings}

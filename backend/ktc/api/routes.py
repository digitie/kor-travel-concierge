"""Web REST API 라우터.

`docs/architecture.md` 3.1의 웹 UX 계약을 노출한다. 장시간 작업은 직접 수행하지
않고 `crawl_runs` 작업만 생성한 뒤 `job_id`를 즉시 반환한다(ADR-13).
실제 ETL 실행은 scheduler 단일 실행자가 담당한다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import get_settings
from ktc.core.database import get_session
from ktc.core.security import require_api_key
from ktc.etl import category_suggestion, place_search, source_resolve
from ktc.etl.youtube_client import YouTubeClient
from ktc.models import (
    CrawlRun,
    ExtractedPlaceCandidate,
    FeatureExport,
    MediaAsset,
    RunSource,
    RunState,
    SourceTarget,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeChannel,
    YoutubePlaylist,
    YoutubeVideo,
)
from ktc.services import (
    audit_service,
    crawl_run_service,
    feature_export_service,
    place_export_service,
    place_service,
    settings_service,
    source_scan_service,
)

# REST API는 버전 프리픽스(`/api/v1`) 아래에 노출한다. 새 버전이 필요하면 동일한
# 패턴으로 `/api/v2` 라우터를 추가한다. 인증(인증 코드)은 라우터 전체에 적용하되
# 로컬 실행에서는 우회된다(`ktc.core.security.require_api_key`).
API_V1_PREFIX = "/api/v1"

router = APIRouter(prefix=API_V1_PREFIX, dependencies=[Depends(require_api_key)])

EXPORT_DESTINATION_LIMIT_DEFAULT = 500
EXPORT_DESTINATION_LIMIT_MAX = 1_000


class HarvestRequest(BaseModel):
    """수집 시작 요청 본문."""

    query: str | None = None
    # channel_id는 `UC...` ID뿐 아니라 채널명/@handle/채널 URL을 받아 백엔드가 표준 ID로 해석한다.
    channel_id: str | None = None
    # playlist_id는 `PL...` ID뿐 아니라 재생목록/시청 URL을 받아 백엔드가 `list=` ID로 해석한다.
    playlist_id: str | None = None
    max_videos: int = 20
    # True면 영상 수집만 수행하고 자막/POI/지오코딩(자막 생성)은 건너뛴다. 사용자가
    # 자막 생성 전에 확인 단계를 거칠 수 있도록 별도 `transcript` 작업으로 분리한다.
    skip_transcript: bool = False
    # 양수면 즉시 1회 수집과 함께 해당 분 간격의 반복 수집 대상(source_target)으로 등록한다.
    repeat_interval_minutes: int | None = Field(default=None, ge=1, le=525_600)
    # 반복 수집 횟수 상한(0이면 무한). repeat_interval_minutes가 있을 때만 의미가 있다.
    repeat_max_runs: int | None = Field(default=None, ge=0)
    # 콘텐츠 유형 필터: both(숏츠+동영상)/shorts(숏츠만)/videos(동영상만).
    content_filter: Literal["both", "shorts", "videos"] = "both"


class HarvestJob(BaseModel):
    """수집 작업 식별자 응답."""

    job_id: str
    state: str


class TranscriptRequest(BaseModel):
    """자막 작업 생성 요청(선택적 부분집합)."""

    # 비우면 harvest 수집 결과 전체를 처리한다. 주면 그 부분집합만 처리한다(예: 품질 시험).
    video_ids: list[str] | None = None


class RunStatusLog(BaseModel):
    """작업 상태 상세 로그 1건."""

    timestamp: str
    level: str = "info"
    message: str
    progress: float | None = None


class HarvestStatus(BaseModel):
    """수집 작업 상태 응답."""

    job_id: str
    state: str
    progress: float
    current_message: str | None = None
    status_logs: list[RunStatusLog] = Field(default_factory=list)
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

    채널/재생목록/검색어 중 하나를 target으로 기록한다. 채널명/@handle/URL과
    재생목록 URL은 표준 ID(`UC...`/`PL...`)로 해석해 저장한다. `repeat_interval_minutes`가
    있으면 반복 수집 대상(source_target)으로도 등록한다.
    """
    canonical_channel: str | None = None
    canonical_playlist: str | None = None

    if payload.channel_id:
        kind, _value = source_resolve.parse_channel_input(payload.channel_id)
        if kind == "id":
            canonical_channel = _value
        else:
            youtube_key = await settings_service.get_secret(session, "youtube_api_key")
            try:
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    client = YouTubeClient(
                        api_key=youtube_key, http_client=http_client
                    )
                    canonical_channel = await source_resolve.resolve_channel_id(
                        client, payload.channel_id
                    )
            except Exception as exc:  # noqa: BLE001 - 해석 실패를 400으로 노출
                raise HTTPException(
                    status_code=400,
                    detail=f"채널을 해석하지 못했습니다: {exc}",
                ) from exc
        if not canonical_channel:
            raise HTTPException(
                status_code=400,
                detail=f"채널을 찾을 수 없습니다: {payload.channel_id}",
            )
        target_type, target_id = "channel", canonical_channel
    elif payload.playlist_id:
        canonical_playlist = source_resolve.parse_playlist_id(payload.playlist_id)
        if not canonical_playlist:
            raise HTTPException(
                status_code=400,
                detail=f"재생목록 URL/ID를 인식할 수 없습니다: {payload.playlist_id}",
            )
        target_type, target_id = "playlist", canonical_playlist
    else:
        if not payload.query:
            raise HTTPException(
                status_code=400,
                detail="검색어/채널/재생목록 중 하나를 입력하세요",
            )
        target_type, target_id = "keyword", payload.query

    run_payload = payload.model_dump()
    run_payload["channel_id"] = canonical_channel
    run_payload["playlist_id"] = canonical_playlist

    run = await crawl_run_service.create_run(
        session,
        job_type="harvest",
        source=RunSource.WEB,
        target_type=target_type,
        target_id=target_id,
        payload=run_payload,
        commit=False,
    )
    if payload.repeat_interval_minutes:
        await source_scan_service.upsert_recurring_target(
            session,
            target_type=target_type,
            source_value=target_id,
            display_name=target_id,
            scan_interval_minutes=payload.repeat_interval_minutes,
            max_runs=payload.repeat_max_runs or 0,
        )
    await audit_service.record(
        session,
        actor_type="web",
        action="harvest.create",
        target_type="crawl_run",
        target_id=str(run.id),
        payload=run_payload,
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
        current_message=run.current_message,
        status_logs=[
            RunStatusLog.model_validate(log)
            for log in crawl_run_service.load_status_logs(run)
        ],
        last_error=run.last_error,
        result=json.loads(run.result_json) if run.result_json else None,
    )


@router.post("/harvest/{job_id}/transcript", response_model=HarvestJob)
async def start_transcript(
    job_id: int,
    payload: TranscriptRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> HarvestJob:
    """수집 완료된 harvest 영상에 자막/후처리 작업을 별도로 생성한다.

    `skip_transcript`로 수집만 끝낸 harvest의 `video_ids`를 받아 `transcript`
    job_type crawl_run을 만든다. 자막 생성 전 사용자 확인 단계를 보장한다.
    요청 body에 `video_ids`를 주면 수집 결과의 부분집합만 처리한다(예: 품질 시험).
    """
    source = await crawl_run_service.get_run(session, job_id)
    if source is None:
        raise HTTPException(status_code=404, detail="job not found")
    if source.job_type != "harvest":
        raise HTTPException(
            status_code=400, detail="transcript는 harvest 작업에만 생성할 수 있다"
        )
    result = json.loads(source.result_json) if source.result_json else {}
    collected = result.get("video_ids") or []
    if not collected:
        raise HTTPException(
            status_code=400, detail="수집된 영상이 없어 자막 작업을 만들 수 없다"
        )
    if payload is not None and payload.video_ids:
        collected_set = set(collected)
        video_ids = [v for v in payload.video_ids if v in collected_set]
        if not video_ids:
            raise HTTPException(
                status_code=400, detail="요청한 video_ids가 수집 결과에 없습니다"
            )
    else:
        video_ids = collected
    run = await crawl_run_service.create_run(
        session,
        job_type="transcript",
        source=RunSource.WEB,
        target_type=source.target_type,
        target_id=source.target_id,
        payload={"video_ids": video_ids, "source_job_id": job_id},
        commit=False,
    )
    await audit_service.record(
        session,
        actor_type="web",
        action="transcript.create",
        target_type="crawl_run",
        target_id=str(run.id),
        payload={"source_job_id": job_id, "video_count": len(video_ids)},
    )
    return HarvestJob(job_id=str(run.id), state=run.state)


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
            "current_message": run.current_message,
            "status_logs": crawl_run_service.load_status_logs(run),
            "retry_count": run.retry_count,
            "last_error": run.last_error,
            "result": json.loads(run.result_json) if run.result_json else None,
            "created_at": run.created_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }
        for run in runs
    ]


@router.get("/place-search")
async def place_search_endpoint(
    q: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """검수용 멀티 provider 장소 검색(Google/Kakao/Naver) + Gemini 의견.

    각 provider를 동시에 호출하고 독립적으로 격리한다. 키 미설정/호출 실패는
    해당 provider를 빈 목록으로 두고 `errors`에 사유를 남긴다.
    """
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="검색어 q가 필요합니다")
    google_key = await settings_service.get_secret(session, "google_places_api_key")
    kakao_key = await settings_service.get_secret(session, "kakao_rest_api_key")
    naver_id = await settings_service.get_secret(session, "naver_search_client_id")
    naver_secret = await settings_service.get_secret(
        session, "naver_search_client_secret"
    )
    errors: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=15.0) as client:

        async def google() -> list[dict[str, Any]]:
            if not google_key:
                raise RuntimeError("GOOGLE_PLACES_API_KEY 미설정")
            return await place_search.search_google_places(
                client, query=query, api_key=google_key
            )

        async def kakao() -> list[dict[str, Any]]:
            if not kakao_key:
                raise RuntimeError("KAKAO_REST_API_KEY 미설정")
            return await place_search.search_kakao(
                client, query=query, api_key=kakao_key
            )

        async def naver() -> list[dict[str, Any]]:
            if not (naver_id and naver_secret):
                raise RuntimeError("NAVER_SEARCH_CLIENT_ID/SECRET 미설정")
            return await place_search.search_naver_local(
                client,
                query=query,
                client_id=naver_id,
                client_secret=naver_secret,
            )

        provider_names = ("google", "kakao", "naver")
        gathered = await asyncio.gather(
            google(), kakao(), naver(), return_exceptions=True
        )

    normalized: dict[str, list[dict[str, Any]]] = {}
    for name, result in zip(provider_names, gathered):
        if isinstance(result, BaseException):
            errors[name] = str(result)
            normalized[name] = []
        else:
            normalized[name] = result

    all_hits = normalized["google"] + normalized["kakao"] + normalized["naver"]
    gemini_opinion: dict[str, Any] | None = None
    if all_hits:
        # Gemini 의견은 보조 정보이므로, 느린 사람-유사 재시도가 검수 검색 응답을
        # 통째로 막지 않도록 짧은 상한을 둔다(초과 시 provider 결과만 반환).
        try:
            runtime = await settings_service.get_llm_runtime(session)
            gemini_opinion = await asyncio.wait_for(
                asyncio.to_thread(
                    place_search.gemini_place_opinion,
                    runtime,
                    query=query,
                    hits=all_hits,
                ),
                timeout=20.0,
            )
        except (asyncio.TimeoutError, TimeoutError):
            errors["gemini"] = "Gemini 의견 시간 초과(20초)"
        except Exception as exc:  # noqa: BLE001 - Gemini 의견 실패는 검색 결과를 막지 않는다
            errors["gemini"] = str(exc)

    return {
        "query": query,
        "google": normalized["google"],
        "kakao": normalized["kakao"],
        "naver": normalized["naver"],
        "gemini": gemini_opinion,
        "errors": errors,
    }


@router.post("/runs/{job_id}/stop")
async def stop_run(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """작업을 중지한다.

    `pending`이면 즉시 `cancelled`로 마감하고, `running`이면 협조적 중지 신호를 건다
    (실행자가 곧 `cancelled`로 마감). 이미 종료된 작업은 400.
    """
    run = await crawl_run_service.get_run(session, job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="job not found")
    prev_state = run.state
    if run.state == RunState.PENDING:
        await crawl_run_service.cancel_pending(session, job_id)
        new_state = RunState.CANCELLED.value
    elif run.state == RunState.RUNNING:
        await crawl_run_service.request_cancel(session, job_id)
        new_state = run.state
    else:
        raise HTTPException(
            status_code=400, detail="이미 종료된 작업은 중지할 수 없습니다"
        )
    await audit_service.record(
        session,
        actor_type="web",
        action="run.stop",
        target_type="crawl_run",
        target_id=str(job_id),
        payload={"prev_state": prev_state},
    )
    return {"job_id": str(job_id), "state": new_state}


@router.post("/runs/{job_id}/restart")
async def restart_run(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """작업을 같은 입력으로 다시 enqueue한다(새 crawl_run 생성)."""
    source = await crawl_run_service.get_run(session, job_id)
    if source is None:
        raise HTTPException(status_code=404, detail="job not found")
    payload = json.loads(source.payload_json) if source.payload_json else None
    run = await crawl_run_service.create_run(
        session,
        job_type=source.job_type,
        source=RunSource.WEB,
        target_type=source.target_type,
        target_id=source.target_id,
        payload=payload,
        commit=False,
    )
    await audit_service.record(
        session,
        actor_type="web",
        action="run.restart",
        target_type="crawl_run",
        target_id=str(run.id),
        payload={"source_job_id": job_id},
    )
    return {"job_id": str(run.id), "state": run.state}


def _source_target_dict(target: Any) -> dict[str, Any]:
    return {
        "id": target.id,
        "target_type": target.target_type,
        "source_value": target.source_value,
        "display_name": target.display_name,
        "is_active": target.is_active,
        "scan_interval_minutes": target.scan_interval_minutes,
        "max_runs": target.max_runs,
        "run_count": target.run_count,
        "next_crawl_at": target.next_crawl_at.isoformat()
        if target.next_crawl_at
        else None,
        "last_crawled_at": target.last_crawled_at.isoformat()
        if target.last_crawled_at
        else None,
        "last_scan_at": target.last_scan_at.isoformat() if target.last_scan_at else None,
        "scan_failure_count": target.scan_failure_count,
        "last_scan_error": target.last_scan_error,
        "created_at": target.created_at.isoformat() if target.created_at else None,
    }


@router.get("/source-targets")
async def list_source_targets(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """반복 수집(스캔 주기) 활성 대상 목록을 반환한다."""
    targets = await source_scan_service.list_recurring_targets(session)
    return [_source_target_dict(target) for target in targets]


@router.delete("/source-targets/{target_id}")
async def delete_source_target(
    target_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """반복 수집 대상을 비활성화한다(watermark 보존)."""
    target = await source_scan_service.deactivate_target(session, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="source target not found")
    await audit_service.record(
        session,
        actor_type="web",
        action="source_target.deactivate",
        target_type="source_target",
        target_id=str(target_id),
    )
    return {"status": "ok"}


class SourceTargetUpdate(BaseModel):
    """반복 수집 대상 수정 요청(제공된 필드만 갱신)."""

    scan_interval_minutes: int | None = Field(default=None, ge=1, le=525_600)
    max_runs: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


@router.patch("/source-targets/{target_id}")
async def update_source_target(
    target_id: int,
    payload: SourceTargetUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """반복 수집 대상의 주기/횟수/활성 여부를 수정한다."""
    target = await source_scan_service.update_recurring_target(
        session,
        target_id,
        scan_interval_minutes=payload.scan_interval_minutes,
        max_runs=payload.max_runs,
        is_active=payload.is_active,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="source target not found")
    await audit_service.record(
        session,
        actor_type="web",
        action="source_target.update",
        target_type="source_target",
        target_id=str(target_id),
        payload=payload.model_dump(exclude_none=True),
    )
    return _source_target_dict(target)


@router.get("/source-targets/{target_id}/videos")
async def list_source_target_videos(
    target_id: int, session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    """반복 수집 대상이 그동안 수집한 동영상(누적)을 최신순으로 반환한다."""
    target = await session.get(SourceTarget, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="source target not found")
    return await _videos_for_source_target(session, target)


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
    sort: str = "latest",
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """확정 여행지 목록을 반환한다."""
    _validate_destination_sort(sort)
    summaries = await place_service.list_place_summaries(
        session, sort=sort, limit=max(1, min(limit, 500))
    )
    return [_place_summary_payload(summary) for summary in summaries]


@router.get("/destinations/export")
async def export_destinations(
    format: str = "xlsx",
    ids: str | None = None,
    sort: str = "mention_count",
    limit: int = EXPORT_DESTINATION_LIMIT_DEFAULT,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """선택 또는 전체 장소 목록을 `xlsx`, `gpx`, `kml`로 내보낸다."""
    _validate_destination_sort(sort)
    try:
        place_ids = _parse_place_ids(ids)
        export_limit = _normalize_destination_export_limit(limit)
        summaries = await place_service.list_place_summaries(
            session, sort=sort, place_ids=place_ids, limit=export_limit
        )
        body, media_type, base_filename = await asyncio.to_thread(
            place_export_service.build_place_export, summaries, format
        )
        filename = _destination_export_filename(
            base_filename,
            sort=sort,
            selected=place_ids is not None,
            exported_count=len(summaries),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/destinations/unmatched")
async def list_unmatched_candidates(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """매칭 실패(`needs_review`) 후보 검수 큐."""
    candidates = await place_service.list_unmatched_candidates(session)
    return [_candidate_payload(candidate) for candidate in candidates]


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
            category_code_selector=category_suggestion.make_default_selector(),
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
        "candidate": _candidate_payload(candidate),
        "place": _place_payload(place) if place else None,
        "mapping_id": mapping.id if mapping else None,
    }


async def _rustfs_status_dict(session: AsyncSession) -> dict[str, Any]:
    """RustFS 연결 상태 + DB 객체 메타데이터 요약(엔드포인트/지표 공용)."""
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
        "public_base_url": settings.RUSTFS_PUBLIC_BASE_URL,
        "console_url": settings.RUSTFS_CONSOLE_URL,
        "object_prefix": settings.RUSTFS_OBJECT_PREFIX,
        "retention_policy": settings.MEDIA_RETENTION_POLICY,
        "health": health,
        "assets": assets,
        "total_objects": sum(asset["count"] for asset in assets),
        "total_size_bytes": sum(asset["size_bytes"] for asset in assets),
    }


@router.get("/storage/rustfs")
async def get_rustfs_status(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """RustFS 연결 상태와 DB에 기록된 객체 메타데이터 요약을 반환한다."""
    return await _rustfs_status_dict(session)


async def _database_counts(session: AsyncSession) -> dict[str, Any]:
    """운영 지표용 주요 테이블 수치를 집계한다."""

    async def _count(stmt: Any) -> int:
        return int((await session.execute(stmt)).scalar_one() or 0)

    candidate_rows = (
        await session.execute(
            select(ExtractedPlaceCandidate.match_status, func.count()).group_by(
                ExtractedPlaceCandidate.match_status
            )
        )
    ).all()
    run_rows = (
        await session.execute(
            select(CrawlRun.state, func.count()).group_by(CrawlRun.state)
        )
    ).all()
    return {
        "youtube_videos": await _count(select(func.count()).select_from(YoutubeVideo)),
        "youtube_channels": await _count(
            select(func.count()).select_from(YoutubeChannel)
        ),
        "youtube_playlists": await _count(
            select(func.count()).select_from(YoutubePlaylist)
        ),
        "travel_places": await _count(select(func.count()).select_from(TravelPlace)),
        "travel_places_geocoded": await _count(
            select(func.count())
            .select_from(TravelPlace)
            .where(TravelPlace.is_geocoded.is_(True))
        ),
        "video_place_mappings": await _count(
            select(func.count()).select_from(VideoPlaceMapping)
        ),
        "feature_exports": await _count(
            select(func.count()).select_from(FeatureExport)
        ),
        "active_recurring_targets": await _count(
            select(func.count())
            .select_from(SourceTarget)
            .where(
                SourceTarget.is_active.is_(True),
                SourceTarget.scan_interval_minutes.is_not(None),
            )
        ),
        "candidates_by_status": {str(s): int(c) for s, c in candidate_rows},
        "runs_by_state": {str(s): int(c) for s, c in run_rows},
    }


@router.get("/metrics")
async def get_metrics(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """운영 상세 지표(스토리지 + DB 수치)를 반환한다."""
    return {
        "storage": await _rustfs_status_dict(session),
        "database": await _database_counts(session),
    }


async def _video_rows(
    session: AsyncSession, video_ids: list[str]
) -> list[dict[str, Any]]:
    """video_id 목록의 동영상 표시 정보를 게시 최신순으로 반환한다(중복 제거)."""
    ids = [vid for vid in dict.fromkeys(video_ids) if vid]
    if not ids:
        return []
    result = await session.execute(
        select(YoutubeVideo, YoutubeChannel.title)
        .join(
            YoutubeChannel,
            YoutubeChannel.channel_id == YoutubeVideo.channel_id,
            isouter=True,
        )
        .where(YoutubeVideo.video_id.in_(ids))
        .order_by(YoutubeVideo.published_at.desc().nullslast())
    )
    return [
        {
            "video_id": video.video_id,
            "title": video.title,
            "url": f"https://www.youtube.com/watch?v={video.video_id}",
            "published_at": video.published_at.isoformat()
            if video.published_at
            else None,
            "duration_seconds": video.duration_seconds,
            "channel_title": channel_title,
        }
        for video, channel_title in result.all()
    ]


def _video_ids_from_result(result_json: str | None) -> list[str]:
    if not result_json:
        return []
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return []
    return [str(vid) for vid in (data.get("video_ids") or [])]


async def _videos_for_source_target(
    session: AsyncSession, target: SourceTarget
) -> list[dict[str, Any]]:
    """반복 대상으로 만들어진 harvest 작업들의 수집 동영상을 누적해 반환한다.

    이 대상으로 enqueue된 crawl_run은 `target_type`+`target_id(=source_value)`가
    일치하므로 그 결과 `video_ids`를 합산한다(직접 1회 수집과 스캔 반복 모두 포함).
    """
    rows = (
        await session.execute(
            select(CrawlRun.result_json)
            .where(
                CrawlRun.job_type == "harvest",
                CrawlRun.target_type == target.target_type,
                CrawlRun.target_id == target.source_value,
            )
            .order_by(CrawlRun.id.desc())
            .limit(200)
        )
    ).all()
    video_ids: list[str] = []
    for (result_json,) in rows:
        video_ids.extend(_video_ids_from_result(result_json))
    return (await _video_rows(session, video_ids))[:200]


@router.get("/runs/{job_id}/videos")
async def list_run_videos(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    """해당 작업이 수집한 동영상 목록을 반환한다."""
    run = await crawl_run_service.get_run(session, job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="job not found")
    return await _video_rows(session, _video_ids_from_result(run.result_json))


# --- 범용 feature 수집 API (ADR-26) ---


@router.get("/features/snapshot")
async def features_snapshot(
    cursor: str | None = None,
    limit: int = Query(
        default=feature_export_service.FEATURE_EXPORT_LIMIT_DEFAULT,
        ge=1,
        le=feature_export_service.FEATURE_EXPORT_LIMIT_MAX,
    ),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """현재 활성 feature 후보를 full snapshot으로 노출한다.

    downstream consumer(`python-krtour-map` 등)가 opaque `cursor`로 전체를
    페이지네이션해 가져간다. REST path에는 특정 consumer 이름을 넣지 않는다.
    """
    try:
        page = await feature_export_service.get_snapshot(
            session, cursor=cursor, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "items": page.items,
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
    }


@router.get("/features/changes")
async def features_changes(
    cursor: str | None = None,
    limit: int = Query(
        default=feature_export_service.FEATURE_EXPORT_LIMIT_DEFAULT,
        ge=1,
        le=feature_export_service.FEATURE_EXPORT_LIMIT_MAX,
    ),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """`upsert`/`reject`/`tombstone` 변경을 incremental로 노출한다."""
    try:
        page = await feature_export_service.get_changes(
            session, cursor=cursor, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "items": page.items,
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
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
    values: dict[str, str] = {}
    for key, value in settings.items():
        str_value = str(value)
        # 비밀 키는 빈 값으로 덮어쓰지 않는다(미입력=변경 없음).
        if key in settings_service.SECRET_ENV_ATTRS and not str_value:
            continue
        values[key] = str_value
    try:
        await settings_service.set_many(session, values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 비밀 값(API 키 등)은 감사 로그에 평문으로 남기지 않는다.
    audit_payload = {
        key: ("***" if key in settings_service.SECRET_ENV_ATTRS and value else value)
        for key, value in settings.items()
    }
    await audit_service.record(
        session,
        actor_type="web",
        action="settings.update",
        target_type="system_settings",
        payload=audit_payload,
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


def _candidate_payload(candidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
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
        "reviewed_at": (
            candidate.reviewed_at.isoformat() if candidate.reviewed_at else None
        ),
        "review_note": candidate.review_note,
    }


def _place_summary_payload(summary: place_service.PlaceSummary) -> dict[str, Any]:
    place = summary.place
    payload = _place_payload(place)
    payload.update(
        {
            "mention_count": summary.mention_count,
            "source_channel_count": summary.source_channel_count,
            "source_videos": [
                {
                    "mapping_id": mention.mapping_id,
                    "video_id": mention.video_id,
                    "video_title": mention.video_title,
                    "video_url": mention.video_url,
                    "channel_id": mention.channel_id,
                    "channel_name": mention.channel_name,
                    "timestamp_start": mention.timestamp_start,
                    "timestamp_end": mention.timestamp_end,
                    "ai_summary": mention.ai_summary,
                    "speaker_note": mention.speaker_note,
                }
                for mention in summary.source_videos
            ],
        }
    )
    return payload


def _validate_destination_sort(sort: str) -> None:
    if sort not in {"latest", "mention_count", "name", "category"}:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 정렬 기준: {sort}")


def _parse_place_ids(raw_ids: str | None) -> list[int] | None:
    if not raw_ids:
        return None
    place_ids: list[int] = []
    for raw_id in raw_ids.split(","):
        value = raw_id.strip()
        if not value:
            continue
        try:
            place_id = int(value)
        except ValueError as exc:
            raise ValueError(f"장소 ID는 숫자여야 한다: {value}") from exc
        if place_id <= 0:
            raise ValueError(f"장소 ID는 1 이상이어야 한다: {value}")
        place_ids.append(place_id)
        if len(place_ids) > EXPORT_DESTINATION_LIMIT_MAX:
            raise ValueError(
                f"한 번에 내보낼 수 있는 장소 ID는 최대 {EXPORT_DESTINATION_LIMIT_MAX}개다."
            )
    return place_ids or None


def _normalize_destination_export_limit(limit: int) -> int:
    return max(1, min(limit, EXPORT_DESTINATION_LIMIT_MAX))


def _destination_export_filename(
    base_filename: str,
    *,
    sort: str,
    selected: bool,
    exported_count: int,
    generated_at: datetime | None = None,
) -> str:
    stem, _, extension = base_filename.rpartition(".")
    stem = stem or base_filename
    extension = extension or "bin"
    scope = "selected" if selected else "all"
    timestamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return (
        f"{_filename_slug(stem)}-{scope}-{exported_count}"
        f"-sort-{_filename_slug(sort)}-{timestamp}.{_filename_slug(extension)}"
    )


def _filename_slug(value: str) -> str:
    chars = [char if char.isalnum() else "-" for char in value.casefold()]
    slug = "-".join(part for part in "".join(chars).split("-") if part)
    return slug or "na"

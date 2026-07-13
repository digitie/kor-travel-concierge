"""Web REST API 라우터.

`docs/architecture.md` 3.1의 웹 UX 계약을 노출한다. 장시간 작업은 직접 수행하지
않고 `crawl_runs` 작업만 생성한 뒤 `job_id`를 즉시 반환한다(ADR-13).
실제 ETL 실행은 scheduler 단일 실행자가 담당한다.
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import get_settings
from ktc.core.database import get_repeatable_read_session, get_session
from ktc.core.security import (
    require_admin_proxy,
    require_api_key,
    resolve_admin_proxy_actor,
)
from ktc.etl import (
    category_catalog,
    llm_client,
    media_store,
    place_search,
    postprocess_service,
    source_resolve,
)
from ktc.etl.youtube_client import YouTubeClient
from ktc.models import (
    LANE_BATCH,
    LANE_INTERACTIVE,
    AssetType,
    CrawlRun,
    CrawlStatus,
    ExtractedPlaceCandidate,
    EvidenceSourceKind,
    FeatureExport,
    GroundingStatus,
    MatchStatus,
    MediaAsset,
    RunAttention,
    RunSource,
    SourceTarget,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeChannel,
    YoutubePlaylist,
    YoutubeVideo,
    YoutubeVideoAnalysisRun,
)
from ktc.services import (
    audit_service,
    crawl_run_service,
    feature_export_service,
    list_pagination,
    login_event_service,
    place_export_service,
    place_service,
    public_api_key_service,
    settings_service,
    source_scan_service,
    theme_service,
)

# REST API는 버전 프리픽스(`/api/v1`) 아래에 노출한다. 새 버전이 필요하면 동일한
# 패턴으로 `/api/v2` 라우터를 추가한다. 인증(인증 코드)은 라우터 전체에 적용하되
# 로컬 실행에서는 우회된다(`ktc.core.security.require_api_key`).
API_V1_PREFIX = "/api/v1"

router = APIRouter(prefix=API_V1_PREFIX, dependencies=[Depends(require_api_key)])

EXPORT_DESTINATION_LIMIT_DEFAULT = 500
EXPORT_DESTINATION_LIMIT_MAX = 1_000
CandidateId = Annotated[
    int,
    Path(ge=1, le=list_pagination.MAX_DB_INTEGER_ID),
]


class HarvestRequest(BaseModel):
    """수집 시작 요청 본문."""

    query: str | None = None
    # channel_id는 `UC...` ID뿐 아니라 채널명/@handle/채널 URL을 받아 백엔드가 표준 ID로 해석한다.
    channel_id: str | None = None
    # playlist_id는 `PL...` ID뿐 아니라 재생목록/시청 URL을 받아 백엔드가 `list=` ID로 해석한다.
    playlist_id: str | None = None
    # 단일 영상 URL/ID(`watch?v=`·`youtu.be`·`/shorts/`·11자 ID). 백엔드가 영상 ID로 해석한다.
    video_id: str | None = None
    # 자동분류 입력: 링크/검색어를 넣으면 백엔드가 재생목록/채널/영상/키워드를 스스로 판별한다.
    auto_input: str | None = None
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
    # True면 증분 워터마크를 무시하고 처음부터 max_videos까지 다시 수집한다(강제 다운로드).
    # 기본(False)은 증분 추가 수집(이미 본 영상 이후만).
    force: bool = False
    # POI 카테고리 매칭 실패 시 쓸 기본 카테고리 코드(unknown=0 포함).
    default_category_code: str | None = None


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
    # 사용자가 드롭다운으로 강제하는 8자리 카탈로그 코드. 주어지면 category_code_suggestion과
    # 표시 category(label)를 이 코드 기준으로 덮어쓴다(API 카테고리 대신).
    category_code: str | None = None
    api_source: str | None = None


class SelectedPlaceHitRequest(BaseModel):
    """검수자가 외부 검색 결과에서 선택한 당시의 원본 snapshot."""

    provider: Literal["google", "kakao", "naver"]
    native_id: str | None = Field(default=None, max_length=512)
    query: str = Field(min_length=1, max_length=500)
    searched_at: datetime
    selected_at: datetime
    name: str = Field(min_length=1)
    address: str | None = None
    road_address: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    category: str | None = None

    @field_validator("searched_at", "selected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("검색·선택 시각에는 timezone이 필요하다")
        return value

    @model_validator(mode="after")
    def require_chronological_selection(self) -> "SelectedPlaceHitRequest":
        if self.selected_at < self.searched_at:
            raise ValueError("선택 시각은 검색 시각보다 빠를 수 없다")
        return self


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
    # 사용자가 드롭다운으로 강제하는 8자리 카탈로그 코드(있으면 label로 category도 덮어씀).
    category_code: str | None = None
    api_source: str | None = None
    selected_hit: SelectedPlaceHitRequest | None = None
    duplicate_resolution: Literal["merge_existing", "create_new"] | None = None
    duplicate_place_id: int | None = Field(default=None, gt=0)
    reviewed_by: str = "web"
    review_note: str | None = None


class DeepResearchRequest(BaseModel):
    """Deep Research 작업 생성 요청."""

    prompt: str | None = None
    max_sources: int = Field(default=8, ge=1, le=20)


class AuditResultRequest(BaseModel):
    """auto-match audit 표본 검토 결과 기록 요청(T-167, G9).

    `accurate=True`=자동확정이 정확, `False`=오확정. 기록은 사후 관측이라 자동확정
    상태(MATCHED·export)를 바꾸지 않는다(실제 되돌리기는 별도 reopen). 검토자(reviewed_by)는
    요청 본문으로 받지 않고 서버가 인증된 admin proxy actor에서 유도한다(provenance 위조 방지).
    """

    accurate: bool
    note: str | None = Field(default=None, max_length=1000)


class AuthEventRequest(BaseModel):
    """Next 로그인/로그아웃 라우트가 기록하는 인증 이벤트."""

    event_type: Literal["login", "logout"]
    outcome: Literal["succeeded", "failed", "denied"]
    attempted_username: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=64)
    client_ip: str | None = Field(default=None, max_length=128)
    user_agent: str | None = None
    next_path: str | None = Field(default=None, max_length=1024)


class LoginEventSummary(BaseModel):
    id: int
    event_type: str
    outcome: str
    attempted_username: str | None
    reason: str | None
    client_ip: str | None
    user_agent: str | None
    next_path: str | None
    created_at: datetime


class PublicApiKeySummary(BaseModel):
    id: int
    label: str | None
    key_hint: str
    scope: Literal["read", "admin"]
    state: str
    created_at: datetime
    created_by: str | None
    revoked_at: datetime | None
    revoked_by: str | None


class PublicApiKeyCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    scope: Literal["read", "admin"] = "read"


class PublicApiKeyCreateResponse(BaseModel):
    key: str
    item: PublicApiKeySummary


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
    # 자동분류: auto_input만 들어오면 재생목록/채널/영상/키워드를 판별해 해당 필드를 채운다.
    if payload.auto_input and not (
        payload.query
        or payload.channel_id
        or payload.playlist_id
        or payload.video_id
    ):
        kind, value = source_resolve.classify_source_input(payload.auto_input)
        field_by_kind = {
            "playlist": "playlist_id",
            "channel": "channel_id",
            "video": "video_id",
            "keyword": "query",
        }
        payload = payload.model_copy(update={field_by_kind[kind]: value})

    canonical_channel: str | None = None
    canonical_playlist: str | None = None
    canonical_video: str | None = None

    if payload.video_id:
        raw_video = payload.video_id.strip()
        canonical_video = source_resolve.parse_video_id(raw_video) or (
            raw_video if source_resolve.is_video_id(raw_video) else None
        )
        if not canonical_video:
            raise HTTPException(
                status_code=400,
                detail=f"영상 URL/ID를 인식할 수 없습니다: {payload.video_id}",
            )
        target_type, target_id = "video", canonical_video
    elif payload.channel_id:
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

    default_category_code = category_catalog.normalize_code(payload.default_category_code)
    if payload.default_category_code and default_category_code is None:
        raise HTTPException(status_code=400, detail="지원하지 않는 기본 카테고리 코드입니다")
    run_payload = payload.model_dump()
    run_payload["default_category_code"] = default_category_code
    run_payload["channel_id"] = canonical_channel
    run_payload["playlist_id"] = canonical_playlist
    if canonical_video:
        run_payload["video_ids"] = [canonical_video]

    # 수집(harvest)은 대량 배치 성격이라 기본 lane(batch)을 쓴다(T-163). 사용자
    # 트리거지만 대화형 레인을 점유시키지 않는다.
    run = await crawl_run_service.create_run(
        session,
        job_type="harvest",
        source=RunSource.WEB,
        target_type=target_type,
        target_id=target_id,
        payload=run_payload,
        commit=False,
    )
    # 단일 영상은 반복 대상 등록을 생략한다(영상 자체는 변하지 않음).
    if payload.repeat_interval_minutes and target_type != "video":
        await source_scan_service.upsert_recurring_target(
            session,
            target_type=target_type,
            source_value=target_id,
            display_name=target_id,
            scan_interval_minutes=payload.repeat_interval_minutes,
            max_runs=payload.repeat_max_runs or 0,
            max_videos=payload.max_videos,
            default_category_code=default_category_code,
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


@router.post("/jobs/poi-batch")
async def trigger_poi_batch(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """미처리(discovered) 영상을 묶음(≤10) POI 작업으로 등록한다(수동, job 단위).

    POI 추출은 묶음 단위라 개별 영상이 아닌 job 단위로만 실행한다. 각 묶음이 하나의
    `poi_batch` 작업이 되어 scheduler가 순차 처리한다(자막 교정→배치 추출→지오코딩).
    """
    rows = await session.execute(
        select(YoutubeVideo.video_id)
        .where(YoutubeVideo.crawl_status == CrawlStatus.DISCOVERED)
        .order_by(YoutubeVideo.crawled_at.desc())
    )
    video_ids = [str(v) for v in rows.scalars().all()]
    if not video_ids:
        return {"enqueued_jobs": 0, "videos": 0, "job_ids": []}
    size = max(1, get_settings().POI_BATCH_MAX_VIDEOS)
    job_ids: list[str] = []
    for start in range(0, len(video_ids), size):
        chunk = video_ids[start : start + size]
        run = await crawl_run_service.create_run(
            session,
            job_type="poi_batch",
            source=RunSource.WEB,
            payload={"video_ids": chunk},
            # 미처리 영상 대량 백로그 등록 — 배치 레인(기본, T-163).
            commit=False,
        )
        job_ids.append(str(run.id))
    await audit_service.record(
        session,
        actor_type="web",
        action="poi_batch.enqueue",
        target_type="crawl_run",
        payload={"videos": len(video_ids), "jobs": len(job_ids)},
    )
    return {"enqueued_jobs": len(job_ids), "videos": len(video_ids), "job_ids": job_ids}


class ReprocessRequest(BaseModel):
    """검수 재처리 요청: 선택한 영상들을 어느 단계부터 다시 처리할지."""

    video_ids: list[str]
    # transcript=자막부터 / correction=교정부터 / poi=POI 추출부터.
    start_stage: Literal["transcript", "correction", "poi"] = "transcript"
    # T-169(수동 whisper 재전사): true면 자막을 whisper 로컬 STT로 강제 재전사한다.
    # auto 게이트(`TRANSCRIPT_WHISPER_ENABLED`)를 우회하고 CPU 무거운 batch 레인으로
    # enqueue하며, transcript 단계부터 다시 처리한다.
    force_whisper: bool = False
    # whisper 모델 크기(예: "small"/"medium"). 비우면 config `WHISPER_MANUAL_MODEL_SIZE`.
    whisper_model: str | None = None


@router.post("/destinations/reprocess")
async def reprocess_videos(
    payload: ReprocessRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """검수에서 선택한 영상들을 지정 단계부터 다시 처리(poi_batch enqueue).

    `start_stage`가 실리면 이미 완료된 영상도 다시 처리한다(worker가 DONE 필터 우회).
    """
    video_ids = list(
        dict.fromkeys(v.strip() for v in payload.video_ids if v and v.strip())
    )[:200]
    if not video_ids:
        raise HTTPException(status_code=400, detail="video_ids required")
    settings = get_settings()

    # 기본 재처리: 사용자 버튼 발원이라 대화형 레인. start_stage는 요청 그대로.
    lane = LANE_INTERACTIVE
    start_stage: str = payload.start_stage
    extra_payload: dict[str, Any] = {}

    if payload.force_whisper:
        # T-169 수동 whisper 재전사: CPU 무거운 전사라 배치 레인으로 보낸다(대화형 아님,
        # T-163). whisper는 transcript 단계에서만 돌므로 항상 transcript부터 재처리한다.
        lane = LANE_BATCH
        start_stage = "transcript"
        model_size = (
            (payload.whisper_model or "").strip()
            or settings.WHISPER_MANUAL_MODEL_SIZE
        )
        extra_payload = {"force_whisper": True, "whisper_model": model_size}
        # duration cap: 1건당 상한 — 유일한 per-item 상한이라 우회를 허용하면 안 된다.
        # whisper는 wall-clock 타임아웃도, to_thread 협조 취소도 없어 수 시간짜리 단일
        # 영상이 batch 단일 레인을 무한 점유해 harvest/스캔을 굶길 수 있다(T-121-E 재발).
        # 라이브 다시보기·프리미어 아카이브는 duration_seconds가 NULL로 저장되므로, 강제
        # whisper는 **알려진 양수 duration이고 cap 이하**인 영상만 허용한다(미상/비정상 거절).
        cap = settings.TRANSCRIPT_WHISPER_FORCE_MAX_DURATION_SECONDS
        rows = await session.execute(
            select(YoutubeVideo.video_id, YoutubeVideo.duration_seconds).where(
                YoutubeVideo.video_id.in_(video_ids)
            )
        )
        durations = {vid: dur for vid, dur in rows.all()}
        unknown_or_invalid = [
            vid
            for vid in video_ids
            if durations.get(vid) is None or durations[vid] <= 0
        ]
        too_long = [
            vid
            for vid in video_ids
            if durations.get(vid) is not None and durations[vid] > cap
        ]
        if unknown_or_invalid or too_long:
            reasons: list[str] = []
            if unknown_or_invalid:
                reasons.append(
                    "길이 미상/비정상 영상은 whisper 재전사 대상에서 제외됩니다: "
                    f"{', '.join(unknown_or_invalid)}"
                )
            if too_long:
                reasons.append(
                    f"duration이 {cap}초를 초과: {', '.join(too_long)}"
                )
            raise HTTPException(status_code=400, detail=". ".join(reasons) + ".")

    size = max(1, settings.POI_BATCH_MAX_VIDEOS)
    job_ids: list[str] = []
    for start in range(0, len(video_ids), size):
        chunk = video_ids[start : start + size]
        run = await crawl_run_service.create_run(
            session,
            job_type="poi_batch",
            source=RunSource.WEB,
            payload={"video_ids": chunk, "start_stage": start_stage, **extra_payload},
            lane=lane,
            commit=False,
        )
        job_ids.append(str(run.id))
    await audit_service.record(
        session,
        actor_type="web",
        action="video.reprocess",
        target_type="crawl_run",
        payload={
            "videos": len(video_ids),
            "jobs": len(job_ids),
            "start_stage": start_stage,
            "force_whisper": payload.force_whisper,
        },
    )
    return {
        "enqueued_jobs": len(job_ids),
        "videos": len(video_ids),
        "job_ids": job_ids,
        "start_stage": start_stage,
        "force_whisper": payload.force_whisper,
    }


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
    source_payload = json.loads(source.payload_json) if source.payload_json else {}
    transcript_payload: dict[str, Any] = {
        "video_ids": video_ids,
        "source_job_id": job_id,
    }
    if source_payload.get("default_category_code"):
        transcript_payload["default_category_code"] = source_payload[
            "default_category_code"
        ]
    run = await crawl_run_service.create_run(
        session,
        job_type="transcript",
        source=RunSource.WEB,
        target_type=source.target_type,
        target_id=source.target_id,
        payload=transcript_payload,
        # 사용자 확인 후 수동 자막 후처리 트리거 — 대화형 레인(T-163). 이 transcript
        # 작업이 낳는 poi_batch child는 배치다(_enqueue_poi_batches, splitter 정책).
        lane=LANE_INTERACTIVE,
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


_TARGET_TYPE_LABELS = {
    "channel": "유튜버",
    "playlist": "재생목록",
    "keyword": "검색어",
    "video": "영상",
}
_JOB_TYPE_LABELS = {
    "harvest": "수집",
    "source_scan": "예약 스캔",
    "video_analysis": "영상 분석",
    "deep_research": "심층 조사",
    "transcript": "자막",
    "poi_batch": "장소 추출(묶음)",
    "geocode": "지오코딩",
    "postprocess": "후처리",
}
_ANALYSIS_RUN_TYPE_LABELS = {
    "transcript_extract": "자막 추출",
    "url_summary": "URL 요약",
    "reconcile": "대조 정리",
}


def _enum_value(value: Any) -> str:
    """str/Enum 어느 쪽이든 비교용 문자열 값으로 정규화한다."""
    return str(getattr(value, "value", value) or "")


def _target_type_label(target_type: Any) -> str:
    key = _enum_value(target_type)
    return _TARGET_TYPE_LABELS.get(key, key)


def _job_type_label(job_type: Any) -> str:
    key = _enum_value(job_type)
    return _JOB_TYPE_LABELS.get(key, key)


async def _resolve_title_map(
    session: AsyncSession, pairs: list[tuple[Any, str | None]]
) -> dict[tuple[str, str], str]:
    """(target_type, target_id) 쌍에서 사람이 읽는 제목 맵을 배치 조회한다(N+1 회피)."""
    channel_ids: set[str] = set()
    playlist_ids: set[str] = set()
    video_ids: set[str] = set()
    for target_type, target_id in pairs:
        if not target_id:
            continue
        key = _enum_value(target_type)
        if key == "channel":
            channel_ids.add(target_id)
        elif key == "playlist":
            playlist_ids.add(target_id)
        elif key == "video":
            video_ids.add(target_id)

    titles: dict[tuple[str, str], str] = {}
    if channel_ids:
        for cid, title in (
            await session.execute(
                select(YoutubeChannel.channel_id, YoutubeChannel.title).where(
                    YoutubeChannel.channel_id.in_(channel_ids)
                )
            )
        ).all():
            if title:
                titles[("channel", cid)] = title
    if playlist_ids:
        for pid, title in (
            await session.execute(
                select(YoutubePlaylist.playlist_id, YoutubePlaylist.title).where(
                    YoutubePlaylist.playlist_id.in_(playlist_ids)
                )
            )
        ).all():
            if title:
                titles[("playlist", pid)] = title
    if video_ids:
        for vid, title in (
            await session.execute(
                select(YoutubeVideo.video_id, YoutubeVideo.title).where(
                    YoutubeVideo.video_id.in_(video_ids)
                )
            )
        ).all():
            if title:
                titles[("video", vid)] = title
    return titles


def _target_label(
    target_type: Any, target_id: str | None, titles: dict[tuple[str, str], str]
) -> str:
    """대상의 사람이 읽는 값(검색어 텍스트 또는 채널/재생목록/영상 제목)."""
    key = _enum_value(target_type)
    if key == "keyword":
        return target_id or ""
    return titles.get((key, target_id)) or (target_id or "")


@router.get("/runs")
async def list_runs(
    state: str | None = Query(default=None, max_length=32),
    terminal: bool = Query(default=False),
    attention: RunAttention | None = Query(default=None),
    user_jobs_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    job_types: str | None = Query(default=None, max_length=649),
    cursor: str | None = Query(
        default=None, max_length=list_pagination.CURSOR_MAX_LENGTH
    ),
    newer_than_id: int | None = Query(
        default=None, ge=0, le=list_pagination.MAX_DB_INTEGER_ID
    ),
    session: AsyncSession = Depends(get_repeatable_read_session),
) -> dict[str, Any]:
    """최근 작업 목록을 반환한다.

    `user_jobs_only=true`는 서버 정본 사용자 작업 유형만, `job_types`(쉼표 구분)는
    지정 유형만 본다. `terminal=true`는 종료 상태만, `attention`은 해당 주의
    상태만 반환해 활성 큐와 이력 조회를 분리한다.
    """
    if user_jobs_only and job_types:
        raise HTTPException(
            status_code=400,
            detail="user_jobs_only와 job_types는 함께 사용할 수 없습니다",
        )
    types = (
        list(crawl_run_service.USER_JOB_TYPES)
        if user_jobs_only
        else (
            [t.strip() for t in job_types.split(",") if t.strip()]
            if job_types
            else None
        )
    )
    if types and (len(types) > 10 or any(len(job_type) > 64 for job_type in types)):
        raise HTTPException(
            status_code=400,
            detail="job_types는 최대 10개, 항목당 64자까지 허용합니다",
        )
    try:
        page = await crawl_run_service.list_runs_page(
            session,
            state=state,
            terminal_only=terminal,
            attention=attention,
            limit=limit,
            job_types=types,
            cursor=cursor,
            newer_than_id=newer_than_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    titles = await _resolve_title_map(
        session, [(run.target_type, run.target_id) for run in page.items]
    )
    return list_pagination.page_payload(
        list_pagination.ListPage(
            items=[_run_summary_dict(run, titles) for run in page.items],
            next_cursor=page.next_cursor,
            has_more=page.has_more,
            total=page.total,
            newest_id=page.newest_id,
            newer_than=page.newer_than,
        )
    )


@router.get("/runs/queue")
async def list_run_queue(
    session: AsyncSession = Depends(get_repeatable_read_session),
) -> dict[str, Any]:
    """사용자 활성 작업 대기열과 미확인 종료 작업 수를 반환한다."""
    snapshot = await crawl_run_service.list_run_queue(session)
    titles = await _resolve_title_map(
        session, [(run.target_type, run.target_id) for run in snapshot.items]
    )
    return {
        "items": [
            _run_summary_dict(run, titles, include_details=False)
            for run in snapshot.items
        ],
        "running_count": snapshot.running_count,
        "pending_count": snapshot.pending_count,
        "open_attention_count": snapshot.open_attention_count,
        "has_more": snapshot.has_more,
        "user_job_types": list(crawl_run_service.USER_JOB_TYPES),
    }


@router.get("/place-search")
async def place_search_endpoint(
    q: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """검수용 멀티 provider 장소 검색(Google/Kakao/Naver) — provider 결과만 즉시 반환.

    각 provider를 동시에 호출하고 독립적으로 격리한다. 키 미설정/호출 실패는
    해당 provider를 빈 목록으로 두고 `errors`에 사유를 남긴다. Gemini 의견은 느려서
    검색 응답을 막지 않도록 별도 `POST /place-search/opinion`으로 분리했다.
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

    async with httpx.AsyncClient(timeout=8.0) as client:

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

    return {
        "query": query,
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "google": normalized["google"],
        "kakao": normalized["kakao"],
        "naver": normalized["naver"],
        "errors": errors,
    }


class PlaceOpinionRequest(BaseModel):
    """`POST /place-search/opinion` 요청 — provider 후보로 Gemini 의견을 구한다."""

    query: str = Field(..., min_length=1)
    hits: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/place-search/opinion")
async def place_search_opinion_endpoint(
    payload: PlaceOpinionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """provider 후보 목록으로 Gemini 의견만 별도로 구한다(대화형: 빠른 단발 호출).

    검색(provider) 응답을 막지 않도록 프런트가 후보를 받은 뒤 비동기로 호출한다.
    Gemini는 단발 호출(`max_attempts=1`)에 짧은 타임아웃을 쓰고, 전체를
    `asyncio.wait_for(12s)`로 상한을 둔다. 실패/초과는 `gemini=null`로 흡수한다.
    """
    query = payload.query.strip()
    if not query or not payload.hits:
        return {"gemini": None, "error": None}
    try:
        runtime = await settings_service.get_llm_runtime(session)
        # thread 격리·rate limiter 예약은 게이트웨이(`llm_client`)가 처리한다(T-161).
        gemini_opinion = await asyncio.wait_for(
            place_search.gemini_place_opinion(
                runtime,
                query=query,
                hits=payload.hits,
                raise_on_error=True,
            ),
            timeout=12.0,
        )
        return {"gemini": gemini_opinion, "error": None}
    except llm_client.GeminiQuotaBusy:
        # 분 윈도우 혼잡(quota_max_wait=0 즉시 반환) — 오도성 "12초 시간 초과" 대신
        # 정확한 사유를 안내한다(잠시 후 재시도하면 성공할 수 있는 상태).
        return {
            "gemini": None,
            "error": "Gemini 쿼터 윈도우 대기 중 — 잠시 후 재시도하세요. 검색 결과는 정상입니다.",
        }
    except (asyncio.TimeoutError, TimeoutError):
        return {
            "gemini": None,
            "error": "Gemini 의견 시간 초과(12초) — 검색 결과는 정상입니다.",
        }
    except Exception as exc:  # noqa: BLE001 - 의견 실패는 검색 흐름을 막지 않는다
        status = getattr(exc, "status_code", None)
        message = str(exc)
        if (
            isinstance(exc, llm_client.GeminiQuotaExceeded)
            or status == 429
            or "429" in message
            or "quota" in message.lower()
            or "RESOURCE_EXHAUSTED" in message
        ):
            error = "Gemini API 쿼터 초과(429) — 검색 결과는 정상입니다."
        else:
            error = "Gemini 의견을 가져오지 못했습니다(일시 오류) — 검색 결과는 정상입니다."
        return {"gemini": None, "error": error}


@router.post("/runs/{job_id}/stop")
async def stop_run(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """작업을 중지한다.

    `pending`이면 즉시 `cancelled`로 마감하고, `running`이면 협조적 중지 신호를 건다
    (실행자가 곧 `cancelled`로 마감). 이미 종료된 작업은 400.
    """
    try:
        transition = await crawl_run_service.stop_run(session, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if transition is None:
        raise HTTPException(status_code=404, detail="job not found")
    await audit_service.record(
        session,
        actor_type="web",
        action="run.stop",
        target_type="crawl_run",
        target_id=str(job_id),
        payload={"prev_state": transition.previous_state},
    )
    return {"job_id": str(job_id), "state": transition.accepted_state}


@router.post("/runs/{job_id}/restart")
async def restart_run(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """terminal 작업을 같은 입력으로 다시 enqueue한다(T-162, 로드맵 PR-34).

    - terminal(done/failed/cancelled) 상태만 재시작할 수 있다(그 외 400).
    - **멱등**: 같은 원본의 pending/running 재시작 run이 이미 있으면 새로 만들지
      않고 그 run을 반환한다(중복 클릭 UX — 409 아님, `created=false`).
    - 새 run에 `restart_of_run_id` lineage를 남기고, 원본의 open/acknowledged
      attention은 superseded로 전이한다.
    """
    try:
        run, created = await crawl_run_service.create_restart_run(
            session, job_id, source=RunSource.WEB.value
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="job not found")
    if created:
        await audit_service.record(
            session,
            actor_type="web",
            action="run.restart",
            target_type="crawl_run",
            target_id=str(run.id),
            payload={"source_job_id": job_id, "restart_of_run_id": job_id},
        )
    return {
        "job_id": str(run.id),
        "state": run.state,
        "restart_of_run_id": str(job_id),
        "created": created,
    }


@router.post("/runs/{job_id}/acknowledge")
async def acknowledge_run(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """실패 작업의 attention을 open→acknowledged로 전이한다(T-162).

    이미 acknowledged면 그대로 반환(멱등). attention이 없거나 superseded/resolved면
    확인할 대상이 없으므로 400.
    """
    run = await crawl_run_service.get_run(session, job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="job not found")
    prev_attention = run.attention
    try:
        run = await crawl_run_service.acknowledge_attention(session, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if run is None:  # pragma: no cover - 위 get_run과 같은 트랜잭션 내 삭제 경합
        raise HTTPException(status_code=404, detail="job not found")
    if prev_attention != run.attention:
        await audit_service.record(
            session,
            actor_type="web",
            action="run.acknowledge",
            target_type="crawl_run",
            target_id=str(job_id),
            payload={"prev_attention": prev_attention, "attention": run.attention},
        )
    return {"job_id": str(job_id), "attention": run.attention}


def _source_target_dict(
    target: Any, titles: dict[tuple[str, str], str] | None = None
) -> dict[str, Any]:
    titles = titles or {}
    # display_name이 source_value(원본 ID)와 다르면 사람이 읽는 이름으로 본다.
    if target.display_name and target.display_name != target.source_value:
        target_label = target.display_name
    else:
        target_label = _target_label(target.target_type, target.source_value, titles)
    return {
        "id": target.id,
        "target_type": target.target_type,
        "target_type_label": _target_type_label(target.target_type),
        "source_value": target.source_value,
        "target_label": target_label,
        "display_name": target.display_name,
        "is_active": target.is_active,
        "scan_interval_minutes": target.scan_interval_minutes,
        "max_runs": target.max_runs,
        "max_videos": target.max_videos,
        "default_category_code": target.default_category_code,
        "default_category_label": category_catalog.label_for(
            target.default_category_code
        ),
        "run_count": target.run_count,
        "next_crawl_at": target.next_crawl_at.isoformat()
        if target.next_crawl_at
        else None,
        "last_crawled_at": target.last_crawled_at.isoformat()
        if target.last_crawled_at
        else None,
        "last_scan_at": target.last_scan_at.isoformat() if target.last_scan_at else None,
        "last_seen_video_published_at": target.last_seen_video_published_at.isoformat()
        if target.last_seen_video_published_at
        else None,
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
    titles = await _resolve_title_map(
        session, [(target.target_type, target.source_value) for target in targets]
    )
    return [_source_target_dict(target, titles) for target in targets]


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
    # 반복 수집 1회당 영상 수(수집개수).
    max_videos: int | None = Field(default=None, ge=1, le=300)
    # POI 카테고리 매칭 실패 시 쓸 기본 카테고리 코드(unknown=0 포함).
    default_category_code: str | None = None


@router.patch("/source-targets/{target_id}")
async def update_source_target(
    target_id: int,
    payload: SourceTargetUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """반복 수집 대상의 주기/횟수/활성 여부를 수정한다."""
    if (
        payload.default_category_code is not None
        and category_catalog.normalize_code(payload.default_category_code) is None
    ):
        raise HTTPException(status_code=400, detail="지원하지 않는 기본 카테고리 코드입니다")
    target = await source_scan_service.update_recurring_target(
        session,
        target_id,
        scan_interval_minutes=payload.scan_interval_minutes,
        max_runs=payload.max_runs,
        is_active=payload.is_active,
        max_videos=payload.max_videos,
        default_category_code=payload.default_category_code,
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
    titles = await _resolve_title_map(
        session, [(target.target_type, target.source_value)]
    )
    return _source_target_dict(target, titles)


@router.get("/source-targets/{target_id}/videos")
async def list_source_target_videos(
    target_id: int, session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    """반복 수집 대상이 그동안 수집한 동영상(누적)을 최신순으로 반환한다."""
    target = await session.get(SourceTarget, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="source target not found")
    return await _videos_for_source_target(session, target)


@router.post("/source-targets/{target_id}/run-now")
async def run_source_target_now(
    target_id: int,
    force: bool = False,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """반복 수집 대상을 즉시 1회 실행한다('지금 진행' / '강제 재실행').

    같은 작업이 이미 실행/대기 중이면 그 작업을 반환하고 새로 만들지 않는다.
    `force=true`(강제 재실행)면 증분 워터마크를 리셋해 대상 영상을 재수집하고
    대상의 미완료 영상을 다시 후처리한다.
    """
    target, run, created = await source_scan_service.run_target_now(
        session, target_id, force=force
    )
    if target is None:
        raise HTTPException(status_code=404, detail="source target not found")
    await audit_service.record(
        session,
        actor_type="web",
        action="source_target.run_now",
        target_type="source_target",
        target_id=str(target_id),
        payload={"run_id": run.id if run else None, "created": created, "force": force},
    )
    return {
        "job_id": str(run.id) if run else None,
        "state": run.state if run else None,
        "created": created,
    }


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
    limit: int = Query(default=100, ge=1, le=500),
    channel_id: str | None = Query(default=None, max_length=128),
    playlist_id: str | None = Query(default=None, max_length=128),
    keyword: str | None = Query(default=None, max_length=255),
    video_id: str | None = Query(default=None, max_length=128),
    category: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=255),
    district: str | None = Query(default=None, max_length=128),
    cursor: str | None = Query(
        default=None, max_length=list_pagination.CURSOR_MAX_LENGTH
    ),
    newer_than_id: int | None = Query(
        default=None, ge=0, le=list_pagination.MAX_DB_INTEGER_ID
    ),
    session: AsyncSession = Depends(get_repeatable_read_session),
) -> dict[str, Any]:
    """확정 여행지 목록을 반환한다.

    `channel_id`/`playlist_id`/`keyword`/`video_id`로 출처(유튜버/재생목록/검색어/영상)별
    필터링한다(작업 상세에서 특정 영상의 POI만 보기).
    """
    _validate_destination_sort(sort)
    try:
        page = await place_service.list_place_summaries_page(
            session,
            sort=sort,
            limit=limit,
            channel_id=channel_id,
            playlist_id=playlist_id,
            keyword=keyword,
            video_id=video_id,
            category=category,
            query=q,
            district=district,
            cursor=cursor,
            newer_than_id=newer_than_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return list_pagination.page_payload(
        list_pagination.ListPage(
            items=[_place_summary_payload(summary) for summary in page.items],
            next_cursor=page.next_cursor,
            has_more=page.has_more,
            total=page.total,
            newest_id=page.newest_id,
            newer_than=page.newer_than,
        )
    )


@router.get("/destinations/facets")
async def list_destination_facets(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """결과 보기 그룹화용 출처 facet(유튜버/재생목록/검색어별 장소 수)을 반환한다."""
    return await place_service.list_place_facets(session)


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
    limit: int = Query(2000, ge=1, le=2000),
    channel_id: str | None = Query(default=None, max_length=128),
    playlist_id: str | None = Query(default=None, max_length=128),
    keyword: str | None = Query(default=None, max_length=255),
    q: str | None = Query(default=None, max_length=255),
    sort: place_service.ReviewCandidateSort = Query(
        default=place_service.ReviewCandidateSort.NEWEST
    ),
    is_domestic: place_service.ReviewCandidateDomesticFilter = Query(
        default=place_service.ReviewCandidateDomesticFilter.ALL
    ),
    status: place_service.ReviewCandidateStatus = Query(
        default=place_service.ReviewCandidateStatus.NEEDS_REVIEW
    ),
    reason: place_service.QueueReason | None = Query(default=None),
    source_kind: EvidenceSourceKind | None = Query(default=None),
    grounding: GroundingStatus | None = Query(default=None),
    cursor: str | None = Query(
        default=None, max_length=list_pagination.CURSOR_MAX_LENGTH
    ),
    newer_than_id: int | None = Query(
        default=None, ge=0, le=list_pagination.MAX_DB_INTEGER_ID
    ),
    session: AsyncSession = Depends(get_repeatable_read_session),
) -> dict[str, Any]:
    """상태·출처·검색 조건으로 조회하는 검수 후보 목록."""
    try:
        page = await place_service.list_unmatched_candidates_page(
            session,
            limit=limit,
            channel_id=channel_id,
            playlist_id=playlist_id,
            keyword=keyword,
            query=q,
            sort=sort,
            is_domestic=(
                None
                if is_domestic is place_service.ReviewCandidateDomesticFilter.ALL
                else is_domestic is place_service.ReviewCandidateDomesticFilter.TRUE
            ),
            status=status,
            queue_reason=reason,
            source_kind=source_kind,
            grounding_status=grounding,
            cursor=cursor,
            newer_than_id=newer_than_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 목록은 경량 payload만 반환한다. 상세 근거(provider_evidence_json 등)는 후보 상세
    # 엔드포인트에서 개별 조회하므로, 2,000행 응답에 무거운 JSONB를 실어 검수 화면을
    # 느리게 만들지 않는다(응답 크기 ~3.8MB → ~1.3MB).
    return list_pagination.page_payload(
        list_pagination.ListPage(
            items=[_candidate_list_payload(candidate) for candidate in page.items],
            next_cursor=page.next_cursor,
            has_more=page.has_more,
            total=page.total,
            newest_id=page.newest_id,
            newer_than=page.newer_than,
        )
    )


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
    if ("latitude" in updates or "longitude" in updates) and place.is_geocoded:
        latest = await place_service.enrich_place_admin_codes_postcommit(
            session, place_id=place.place_id
        )
        if latest is None:
            raise HTTPException(status_code=404, detail="place not found")
        place = latest
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
        # 장소 상세에서 사용자가 직접 트리거 — 대화형 레인(T-163).
        lane=LANE_INTERACTIVE,
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


@router.get("/categories")
async def list_categories() -> list[dict[str, Any]]:
    """검수/보정 시 강제 선택할 8자리 카테고리 카탈로그(krtour 코드표 사본, T-070).

    프런트 드롭다운이 코드를 골라 `category_code`로 보내면, 확정 장소의
    `category_code_suggestion`과 표시 `category`를 그 코드 기준으로 강제한다.
    """
    return [
        {
            "code": row["code"],
            "label": row["label"],
            "depth": row.get("depth"),
            "tier1_name": row.get("tier1_name"),
        }
        for row in category_catalog.ui_categories()
    ]


@router.get("/categories/match")
async def match_category(q: str | None = None) -> dict[str, Any]:
    """외부 검색결과 카테고리 문자열(예: '음식점 > 한식 > 한정식')을 카탈로그 8자리
    코드로 근사 매핑한다(LLM 없이 키워드 겹침). 매칭이 없으면 `match`는 null."""
    return {"match": category_catalog.match_label(q)}


@router.post("/destinations/unmatched/{candidate_id}/resolve")
async def resolve_unmatched_candidate(
    candidate_id: CandidateId,
    payload: ResolveCandidateRequest,
    request: Request,
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
            "category_code": payload.category_code,
            "api_source": payload.api_source,
        }
    try:
        actor = resolve_admin_proxy_actor(request, get_settings()) or "unverified-web"
        candidate, place, mapping = await place_service.resolve_candidate(
            session,
            candidate_id=candidate_id,
            action=payload.action,
            reviewed_by=actor,
            reviewer_type="web",
            review_note=payload.review_note,
            place_id=payload.place_id,
            place_data=place_data,
            resolution_evidence=(
                payload.selected_hit.model_dump(mode="json")
                if payload.selected_hit
                else None
            ),
            duplicate_resolution=payload.duplicate_resolution,
            duplicate_place_id=payload.duplicate_place_id,
            commit=False,
        )
    except place_service.ProviderPersistenceDisabled as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "provider_persistence_disabled", "message": str(exc)},
        ) from exc
    except place_service.NearbyPlaceConfirmationRequired as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "nearby_place_confirmation_required",
                "nearby_places": exc.nearby_places,
            },
        ) from exc
    except place_service.CandidateResolveConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resolution = place_service.latest_candidate_resolution(candidate)
    await audit_service.record(
        session,
        actor_type="web",
        action="candidate.resolve",
        target_type="extracted_place_candidate",
        target_id=str(candidate_id),
        payload={
            "request": payload.model_dump(mode="json", exclude_none=True),
            "resolution": resolution,
        },
    )
    if place is not None:
        await place_service.enrich_place_admin_codes_postcommit(
            session, place_id=place.place_id
        )
    candidate, place, mapping = await place_service.authoritative_candidate_resolution(
        session, candidate_id=candidate_id
    )
    return {
        "status": "resolved",
        "candidate": _candidate_payload(candidate),
        "place": _place_payload(place) if place else None,
        "mapping_id": mapping.id if mapping else None,
    }


@router.post("/destinations/unmatched/{candidate_id}/reopen")
async def reopen_unmatched_candidate(
    candidate_id: CandidateId, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """soft delete/제외(`ignored`)된 후보를 검수 대기로 복귀한다(T-160, PR-09 백엔드).

    - soft deleted → 삭제 필드 clear + `needs_review` + export `pending`.
    - `ignored` → `needs_review` + `pending`.
    - 이미 `needs_review` → 409(복귀할 것이 없음).
    - `matched`/`user_corrected` → 400(범위 밖 — 장소 정리 정책은 T-184).
    """
    try:
        candidate, reopened_from = await place_service.reopen_candidate(
            session, candidate_id=candidate_id
        )
    except place_service.CandidateReopenConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except place_service.CandidateReopenUnsupportedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await audit_service.record(
        session,
        actor_type="web",
        action="candidate.reopen",
        target_type="extracted_place_candidate",
        target_id=str(candidate_id),
        payload={"reopened_from": reopened_from},
    )
    return {
        "status": "reopened",
        "reopened_from": reopened_from,
        "candidate": _candidate_payload(candidate),
    }


async def _video_detail_dict(
    session: AsyncSession, video_id: str | None
) -> dict[str, Any] | None:
    """영상 1건의 상세 표시 정보(설명 포함)를 반환한다."""
    if not video_id:
        return None
    row = (
        await session.execute(
            select(YoutubeVideo, YoutubeChannel.title)
            .join(
                YoutubeChannel,
                YoutubeChannel.channel_id == YoutubeVideo.channel_id,
                isouter=True,
            )
            .where(YoutubeVideo.video_id == video_id)
        )
    ).first()
    if row is None:
        return None
    video, channel_title = row
    return {
        "video_id": video.video_id,
        "title": video.title,
        "url": video.canonical_url
        or video.url
        or f"https://www.youtube.com/watch?v={video.video_id}",
        "channel_id": video.channel_id,
        "channel_title": channel_title or video.channel_name,
        "source_search_query": video.source_search_query,
        "published_at": video.published_at.isoformat()
        if video.published_at
        else None,
        "duration_seconds": video.duration_seconds,
        "description": video.description_gemini_corrected or video.description_raw,
    }


@router.get("/destinations/candidates/{candidate_id}/transcript")
async def get_candidate_transcript(
    candidate_id: CandidateId, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """후보의 출처 영상에 대한 보정 자막(없으면 원본 자막) 텍스트를 반환한다.

    RustFS에 저장된 최신 `transcript_corrected` 자산을 우선 읽고, 없으면 원본
    `transcript`로 폴백한다. 둘 다 없으면 `text`/`kind`는 null."""
    candidate = await session.get(ExtractedPlaceCandidate, candidate_id)
    if candidate is None or candidate.deleted_at is not None:
        raise HTTPException(status_code=404, detail="candidate not found")
    store = postprocess_service._make_media_store(get_settings())
    text = await media_store.load_latest_asset_text(
        session,
        store,
        video_id=candidate.video_id,
        asset_type=AssetType.TRANSCRIPT_CORRECTED.value,
    )
    kind: str | None = "corrected" if text else None
    if not text:
        text = await media_store.load_latest_asset_text(
            session,
            store,
            video_id=candidate.video_id,
            asset_type=AssetType.TRANSCRIPT.value,
        )
        kind = "raw" if text else None
    return {"text": text, "kind": kind, "video_id": candidate.video_id}


@router.get("/destinations/candidates/{candidate_id}/detail")
async def get_candidate_detail(
    candidate_id: CandidateId, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """검수 후보 1건의 상세 정보(영상·근거·동일 영상의 다른 후보)를 반환한다.

    soft delete된 후보는 404다(T-160 — 삭제 후보 열람 UI는 T-184에서 다룬다).
    """
    list_item = await place_service.get_candidate_list_item(session, candidate_id)
    if list_item is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    candidate = list_item.candidate

    video = await _video_detail_dict(session, candidate.video_id)

    source_run: dict[str, Any] | None = None
    if candidate.analysis_run_id is not None:
        run = await session.get(YoutubeVideoAnalysisRun, candidate.analysis_run_id)
        if run is not None:
            source_run = {
                "id": run.id,
                "run_type": run.run_type,
                "run_type_label": _ANALYSIS_RUN_TYPE_LABELS.get(
                    run.run_type, run.run_type
                ),
                "state": run.state,
                "model": run.model,
                "created_at": run.created_at.isoformat() if run.created_at else None,
            }

    sibling_rows = (
        await session.execute(
            select(
                ExtractedPlaceCandidate.id,
                ExtractedPlaceCandidate.ai_place_name,
                ExtractedPlaceCandidate.match_status,
                ExtractedPlaceCandidate.candidate_category,
                func.coalesce(
                    VideoPlaceMapping.place_id,
                    ExtractedPlaceCandidate.matched_place_id,
                ),
            )
            .join(
                VideoPlaceMapping,
                VideoPlaceMapping.place_candidate_id == ExtractedPlaceCandidate.id,
                isouter=True,
            )
            .where(
                ExtractedPlaceCandidate.video_id == candidate.video_id,
                ExtractedPlaceCandidate.id != candidate.id,
                ExtractedPlaceCandidate.deleted_at.is_(None),
            )
            .order_by(ExtractedPlaceCandidate.id)
        )
    ).all()

    return {
        "list_item": _candidate_list_payload(list_item),
        "candidate": {
            "id": candidate.id,
            "video_id": candidate.video_id,
            "source_channel_id": candidate.source_channel_id,
            "source_playlist_id": candidate.source_playlist_id,
            "ai_place_name": candidate.ai_place_name,
            "location_hint": candidate.location_hint,
            "candidate_category": candidate.candidate_category,
            "candidate_category_code": place_service.candidate_category_code(candidate),
            "match_status": candidate.match_status,
            "confidence_score": _safe_confidence_score(candidate.confidence_score),
            "grounding_status": candidate.grounding_status,
            "is_domestic": candidate.is_domestic,
            "speaker_note": candidate.speaker_note,
            "source_kind": candidate.source_kind,
            "feature_export_status": candidate.feature_export_status,
            "timestamp_start": candidate.timestamp_start,
            "timestamp_end": candidate.timestamp_end,
            "source_text": candidate.source_text,
        },
        "video": video,
        "source_run": source_run,
        "provider_evidence": candidate.provider_evidence_json,
        "sibling_candidates": [
            {
                "id": sid,
                "ai_place_name": name,
                "match_status": status,
                "candidate_category": category,
                "place_id": place_id,
            }
            for sid, name, status, category, place_id in sibling_rows
        ],
    }


# --- auto-match audit 표본 (T-167, 로드맵 PR-14 개정판, G9) ---
# 리터럴 `/destinations/audit/*`는 int `{place_id}`/`{candidate_id}` 경로와 세그먼트가
# 겹치지 않지만, 명확성을 위해 파라미터 경로보다 먼저 등록한다.


@router.get("/destinations/audit/samples")
async def list_audit_sample_queue(
    status: Literal["pending", "accurate", "misconfirmed"] | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """auto-match audit 표본 큐를 미검토 우선·최신순으로 반환한다(G9).

    표본은 자동확정 당시의 결정을 검토하는 역사 표본이다. 이후 별도 reopen으로 현재
    `match_status`가 달라져도 표본과 판정 이력을 유지하며, 응답에 현재 상태를 함께 싣는다.
    """
    items = await place_service.list_audit_samples(
        session, status=status, limit=limit
    )
    return {
        "items": [
            {
                "candidate_id": item.candidate.id,
                "video_id": item.candidate.video_id,
                "video_title": item.video_title,
                "ai_place_name": item.candidate.ai_place_name,
                "matched_place_id": item.candidate.matched_place_id,
                "place_name": item.place_name,
                "confidence_score": _safe_confidence_score(
                    item.candidate.confidence_score
                ),
                "grounding_status": item.candidate.grounding_status,
                "match_status": item.candidate.match_status,
                "audit_status": item.candidate.audit_status,
                "audit_reviewed_by": item.candidate.audit_reviewed_by,
                "audit_reviewed_at": (
                    item.candidate.audit_reviewed_at.isoformat()
                    if item.candidate.audit_reviewed_at
                    else None
                ),
                "audit_note": item.candidate.audit_note,
                "reviewed_at": (
                    item.candidate.reviewed_at.isoformat()
                    if item.candidate.reviewed_at
                    else None
                ),
            }
            for item in items
        ],
    }


@router.get("/destinations/audit/summary")
async def get_audit_summary(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """auto-match audit 표본의 오확정률(자동확정 뒤집힘 비율)을 반환한다(§7 G9 지표).

    `misconfirmation_rate = misconfirmed / (accurate + misconfirmed)`. 검토 표본이 없으면
    null(표본 0을 정밀도 100%로 오도하지 않는다).
    """
    return await place_service.audit_summary(session)


@router.post("/destinations/audit/{candidate_id}")
async def submit_audit_result(
    candidate_id: CandidateId,
    payload: AuditResultRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """audit 표본에 사람 검토 결과(정확/오확정)를 기록한다(G9).

    사후 관측이라 자동확정(MATCHED)·export 상태를 바꾸지 않는다. 표본이 아니면 409,
    없는/삭제된 후보면 404. 검토자는 인증된 admin proxy actor에서 유도한다(위조 방지).
    """
    actor = resolve_admin_proxy_actor(request, get_settings()) or "unverified-web"
    try:
        candidate = await place_service.record_audit_result(
            session,
            candidate_id=candidate_id,
            accurate=payload.accurate,
            reviewed_by=actor,
            note=payload.note,
            commit=False,
        )
    except (
        place_service.AuditNotSampledError,
        place_service.AuditResultConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await audit_service.record(
        session,
        actor_type="web",
        action="candidate.audit_result",
        target_type="extracted_place_candidate",
        target_id=str(candidate_id),
        payload={
            "audit_status": candidate.audit_status,
            "accurate": payload.accurate,
        },
    )
    return {
        "candidate_id": candidate.id,
        "audit_status": candidate.audit_status,
        "audit_reviewed_by": candidate.audit_reviewed_by,
        "audit_reviewed_at": (
            candidate.audit_reviewed_at.isoformat()
            if candidate.audit_reviewed_at
            else None
        ),
        # audit은 사후 관측 — 자동확정 상태는 그대로 유지됨을 응답으로 확인시킨다.
        "match_status": candidate.match_status,
        "feature_export_status": candidate.feature_export_status,
    }


@router.get("/destinations/{place_id}/merge-suggestions")
async def get_place_merge_suggestions(
    place_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """확정 장소의 잠재 중복(정규화 이름 유사 + 근접) 병합 제안을 반환한다(T-167, D6).

    **제안**일 뿐 자동으로 상태를 바꾸지 않는다(자동 병합 금지 — 실제 병합은 사람이
    판단해 `merge_places`로 실행한다).
    """
    try:
        suggestions = await place_service.merge_suggestions_for_place(
            session, place_id=place_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "place_id": place_id,
        "suggestions": [
            {
                "place_id": suggestion.place.place_id,
                "name": suggestion.place.name,
                "official_address": suggestion.place.official_address,
                "road_address": suggestion.place.road_address,
                "latitude": suggestion.place.latitude,
                "longitude": suggestion.place.longitude,
                "category": suggestion.place.category,
                "distance_m": round(suggestion.distance_m, 1),
            }
            for suggestion in suggestions
        ],
    }


@router.delete("/destinations/candidates/{candidate_id}")
async def delete_candidate(
    candidate_id: CandidateId,
    reason: str | None = Query(None, max_length=255),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """검수 후보를 soft delete 한다(T-160 — 행·export ledger 보존, reopen으로 복구 가능).

    검수 대기(`needs_review`) 상태만 삭제한다. stale UI 요청이 도착하기 전
    다른 검수자가 제외·확정한 후보는 서비스의 `FOR UPDATE` 아래서 409로
    거부한다. 확정 장소와 연결된(매핑 보유) 후보의 409도 유지한다.
    이미 export된 후보는 같은 트랜잭션에서 ledger를 tombstone으로 전환해
    downstream consumer가 `changes`로 제거를 전달받는다.
    """
    delete_reason = (reason or "").strip() or "검수 큐에서 삭제"
    try:
        summary = await place_service.soft_delete_candidates(
            session,
            [candidate_id],
            reason=delete_reason,
            deleted_by="web",
            force=False,
            expected_status=MatchStatus.NEEDS_REVIEW,
        )
    except place_service.CandidateStatusConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except place_service.CandidateMappingConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="확정 장소와 연결된 후보는 삭제할 수 없습니다.",
        ) from exc
    if summary.deleted_candidates == 0:
        raise HTTPException(status_code=404, detail="candidate not found")
    await audit_service.record(
        session,
        actor_type="web",
        action="candidate.delete",
        target_type="extracted_place_candidate",
        target_id=str(candidate_id),
        payload={
            "soft_delete": True,
            "reason": delete_reason,
            "tombstoned_exports": summary.tombstoned_exports,
        },
    )
    return {"deleted": True, "id": candidate_id}


@router.delete("/destinations/{place_id}")
async def delete_place(
    place_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """확정 장소를 삭제한다.

    장소를 만든 후보는 검수 큐(`needs_review`)로 되돌리고, 영상 매핑은 삭제, 미디어
    자산은 링크만 해제한다. feature export ledger를 동기화해 이미 내보낸 feature는
    tombstone으로 전환한다(downstream consumer 반영). 감사 로그 기록 시 단일 커밋.
    """
    try:
        reverted = await place_service.delete_place(session, place_id=place_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # delete_place가 되돌린 후보를 dirty로 표시했으므로, 전량 sync 대신 dirty consume으로
    # 그 후보들만 tombstone 회수한다(T-171 — 상시 O(N) sync 제거).
    await feature_export_service.sync_dirty(session, commit=False)
    await audit_service.record(
        session,
        actor_type="web",
        action="place.delete",
        target_type="travel_place",
        target_id=str(place_id),
        payload={"reverted_candidate_ids": [c.id for c in reverted]},
    )
    return {
        "deleted": True,
        "place_id": place_id,
        "reverted_candidates": len(reverted),
    }


class ExcludeVideoRequest(BaseModel):
    """동영상 제외 요청(선택 사유)."""

    reason: str | None = None


@router.post("/destinations/videos/{video_id}/exclude")
async def exclude_video(
    video_id: str,
    payload: ExcludeVideoRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """관련 없거나 질 낮은 동영상을 제외(블록리스트)하고 관련 POI를 삭제한다.

    영상을 `is_excluded`로 표시해 이후 수집에서 다시 받지 않고 스킵하며, 이 영상의
    추출 후보·언급 매핑을 삭제하고 고아가 된 장소만 함께 삭제한다(다른 영상이
    언급하는 장소는 보존). 영상을 찾지 못하면 404.
    """
    reason = payload.reason if payload else None
    result = await place_service.exclude_video(session, video_id, reason=reason)
    if result is None:
        raise HTTPException(status_code=404, detail="video not found")
    await audit_service.record(
        session,
        actor_type="web",
        action="video.exclude",
        target_type="youtube_video",
        target_id=video_id,
        payload=result,
    )
    return result


@router.get("/destinations/{place_id}/detail")
async def get_destination_detail(
    place_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """확정 장소의 상세 정보(설명·통계·등장 영상별 근거)를 반환한다."""
    place = await place_service.get_place(session, place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="place not found")

    rows = (
        await session.execute(
            select(VideoPlaceMapping, YoutubeVideo, YoutubeChannel.title)
            .join(
                YoutubeVideo,
                YoutubeVideo.video_id == VideoPlaceMapping.video_id,
                isouter=True,
            )
            .join(
                YoutubeChannel,
                YoutubeChannel.channel_id == YoutubeVideo.channel_id,
                isouter=True,
            )
            .where(VideoPlaceMapping.place_id == place_id)
            .order_by(VideoPlaceMapping.video_id, VideoPlaceMapping.id)
        )
    ).all()

    by_video: dict[str, dict[str, Any]] = {}
    channels: set[str] = set()
    total_mentions = 0
    for mapping, video, channel_title in rows:
        total_mentions += 1
        vid = mapping.video_id
        if video is not None and video.channel_id:
            channels.add(video.channel_id)
        group = by_video.get(vid)
        if group is None:
            group = {
                "video_id": vid,
                "title": video.title if video is not None else vid,
                "url": (
                    (video.canonical_url or video.url)
                    if video is not None
                    else f"https://www.youtube.com/watch?v={vid}"
                ),
                "channel_title": channel_title
                or (video.channel_name if video is not None else None),
                "published_at": video.published_at.isoformat()
                if (video is not None and video.published_at)
                else None,
                "mention_count": 0,
                "mentions": [],
            }
            by_video[vid] = group
        group["mention_count"] += 1
        group["mentions"].append(
            {
                "timestamp_start": mapping.timestamp_start,
                "timestamp_end": mapping.timestamp_end,
                "source_kind": mapping.source_kind,
                "source_text": mapping.ai_summary,
                "speaker_note": mapping.speaker_note,
            }
        )

    source_videos = sorted(
        by_video.values(),
        key=lambda item: item["published_at"] or "",
        reverse=True,
    )

    return {
        "place": {
            "place_id": place.place_id,
            "name": place.name,
            "category": place.category,
            "category_code_suggestion": place.category_code_suggestion,
            "sigungu_code": place.sigungu_code,
            "sigungu_name": place.sigungu_name,
            "legal_dong_code": place.legal_dong_code,
            "legal_dong_name": place.legal_dong_name,
            "official_address": place.official_address,
            "road_address": place.road_address,
            "latitude": place.latitude,
            "longitude": place.longitude,
            "is_geocoded": place.is_geocoded,
            "description": place.description,
            "gemini_enriched_description": place.gemini_enriched_description,
            "detailed_research_content": place.detailed_research_content,
        },
        "stats": {
            "mention_count": total_mentions,
            "video_count": len(by_video),
            "channel_count": len(channels),
        },
        "source_videos": source_videos,
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
            select(ExtractedPlaceCandidate.match_status, func.count())
            .where(ExtractedPlaceCandidate.deleted_at.is_(None))
            .group_by(ExtractedPlaceCandidate.match_status)
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


def _run_payload(run: CrawlRun) -> dict[str, Any]:
    """crawl_run의 입력 payload(dict)를 안전하게 파싱한다."""
    if not run.payload_json:
        return {}
    try:
        return json.loads(run.payload_json) or {}
    except (TypeError, ValueError):
        return {}


def _run_max_videos(run: CrawlRun) -> int | None:
    """입력 payload의 max_videos(최대 영상 수). 완료 전에도 노출되도록 result가 아닌
    payload에서 읽는다."""
    value = _run_payload(run).get("max_videos")
    return int(value) if isinstance(value, (int, float)) else None


def _run_default_category_code(run: CrawlRun) -> str | None:
    value = _run_payload(run).get("default_category_code")
    return category_catalog.normalize_code(str(value)) if value is not None else None


def _run_summary_dict(
    run: CrawlRun,
    titles: dict[Any, Any],
    *,
    include_details: bool = True,
) -> dict[str, Any]:
    """crawl_run을 작업 목록/상세 공통 요약 dict로 직렬화한다."""
    return {
        "job_id": str(run.id),
        "job_type": run.job_type,
        "job_type_label": _job_type_label(run.job_type),
        # 워커 레인(T-163, additive). interactive=사용자 직접, batch=스케줄러/대량.
        "lane": run.lane,
        "source": run.source,
        "target_type": run.target_type,
        "target_type_label": _target_type_label(run.target_type),
        "target_id": run.target_id,
        "target_label": _target_label(run.target_type, run.target_id, titles),
        "state": run.state,
        "progress": run.progress,
        "current_message": run.current_message,
        "max_videos": _run_max_videos(run),
        "default_category_code": _run_default_category_code(run),
        "default_category_label": category_catalog.label_for(
            _run_default_category_code(run)
        ),
        "status_logs": (
            crawl_run_service.load_status_logs(run) if include_details else []
        ),
        "retry_count": run.retry_count,
        "last_error": run.last_error,
        # T-162: 재시작 lineage·실패 attention(additive — T-180/T-181이 소비).
        "restart_of_run_id": (
            str(run.restart_of_run_id) if run.restart_of_run_id is not None else None
        ),
        "attention": run.attention,
        "result": (
            json.loads(run.result_json)
            if include_details and run.result_json
            else None
        ),
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _video_ids_for_run(run: CrawlRun) -> list[str]:
    """완료 결과(result_json)의 video_ids에 입력 payload의 video_ids를 합친다.
    진행 중(결과 전)에도 이미 적재된 영상·POI를 노출하기 위함이다."""
    ids = _video_ids_from_result(run.result_json)
    ids.extend(str(vid) for vid in (_run_payload(run).get("video_ids") or []))
    return ids


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
    # 채널 대상은 harvest 결과 video_ids가 비어 있어도 channel_id로 적재된
    # 영상을 보강해 누적 목록이 비지 않게 한다.
    if _enum_value(target.target_type) == "channel":
        chan_rows = (
            await session.execute(
                select(YoutubeVideo.video_id)
                .where(YoutubeVideo.channel_id == target.source_value)
                .order_by(YoutubeVideo.published_at.desc().nullslast())
                .limit(200)
            )
        ).all()
        video_ids.extend(vid for (vid,) in chan_rows)
    return (await _video_rows(session, video_ids))[:200]


@router.get("/runs/{job_id}/videos")
async def list_run_videos(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    """해당 작업이 수집한 동영상 목록을 반환한다(진행 중에도 적재분 노출)."""
    run = await crawl_run_service.get_run(session, job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="job not found")
    return await _video_rows(session, _video_ids_for_run(run))


@router.get("/runs/{job_id}/places")
async def list_run_places(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    """해당 작업의 영상에서 추출된 POI를 반환한다.

    확정 장소(`confirmed`)와 검수 대기 후보(`needs_review`)를 함께 노출해, 프런트가
    상태에 따라 결과 뷰/검수 뷰로 이동할 수 있게 한다(진행 중에도 적재분 노출).
    """
    run = await crawl_run_service.get_run(session, job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="job not found")
    video_ids = [vid for vid in dict.fromkeys(_video_ids_for_run(run)) if vid]
    if not video_ids:
        return []

    places: list[dict[str, Any]] = []
    seen_places: set[int] = set()
    confirmed = await session.execute(
        select(TravelPlace.place_id, TravelPlace.name)
        .join(VideoPlaceMapping, VideoPlaceMapping.place_id == TravelPlace.place_id)
        .where(VideoPlaceMapping.video_id.in_(video_ids))
    )
    for place_id, name in confirmed.all():
        if place_id in seen_places:
            continue
        seen_places.add(place_id)
        places.append(
            {
                "kind": "place",
                "place_id": place_id,
                "candidate_id": None,
                "name": name,
                "status": "confirmed",
                "is_domestic": None,
            }
        )

    candidates = await session.execute(
        select(
            ExtractedPlaceCandidate.id,
            ExtractedPlaceCandidate.ai_place_name,
            ExtractedPlaceCandidate.is_domestic,
        )
        .where(
            ExtractedPlaceCandidate.video_id.in_(video_ids),
            ExtractedPlaceCandidate.match_status == MatchStatus.NEEDS_REVIEW,
            ExtractedPlaceCandidate.deleted_at.is_(None),
        )
        .order_by(ExtractedPlaceCandidate.id.desc())
    )
    seen_candidate_names: set[str] = set()
    for candidate_id, name, is_domestic in candidates.all():
        key = (name or "").strip().lower()
        if key and key in seen_candidate_names:
            continue
        if key:
            seen_candidate_names.add(key)
        places.append(
            {
                "kind": "candidate",
                "place_id": None,
                "candidate_id": candidate_id,
                "name": name,
                "status": "needs_review",
                "is_domestic": is_domestic,
            }
        )
    return places[:300]


@router.get("/runs/{job_id}")
async def get_run(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """단일 작업 요약(작업 상세 페이지용)."""
    run = await crawl_run_service.get_run(session, job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="job not found")
    titles = await _resolve_title_map(session, [(run.target_type, run.target_id)])
    return _run_summary_dict(run, titles)


@router.get("/runs/{job_id}/video-stats")
async def list_run_video_stats(
    job_id: int, session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    """작업의 영상별 POI 집계(자동/검수필요/수동완료).

    버킷 정의: `poi_auto`=`matched`(자동 매칭 확정), `poi_needs_review`=`needs_review`
    (검수 대기), `poi_resolved`=`user_corrected`(수동 검수 완료). `ignored`(제외)는
    합계에서 뺀다.
    """
    run = await crawl_run_service.get_run(session, job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="job not found")
    video_ids = [vid for vid in dict.fromkeys(_video_ids_for_run(run)) if vid]
    if not video_ids:
        return []
    rows = await session.execute(
        select(
            ExtractedPlaceCandidate.video_id,
            ExtractedPlaceCandidate.match_status,
            func.count(),
        )
        .where(
            ExtractedPlaceCandidate.video_id.in_(video_ids),
            ExtractedPlaceCandidate.deleted_at.is_(None),
        )
        .group_by(
            ExtractedPlaceCandidate.video_id, ExtractedPlaceCandidate.match_status
        )
    )
    counts: dict[str, dict[str, int]] = {}
    for vid, status, n in rows.all():
        bucket = counts.setdefault(vid, {"auto": 0, "needs_review": 0, "resolved": 0})
        if status == MatchStatus.MATCHED.value:
            bucket["auto"] += int(n)
        elif status == MatchStatus.NEEDS_REVIEW.value:
            bucket["needs_review"] += int(n)
        elif status == MatchStatus.USER_CORRECTED.value:
            bucket["resolved"] += int(n)
    out: list[dict[str, Any]] = []
    for video in await _video_rows(session, video_ids):
        c = counts.get(
            video["video_id"], {"auto": 0, "needs_review": 0, "resolved": 0}
        )
        out.append(
            {
                "video_id": video["video_id"],
                "title": video["title"],
                "url": video["url"],
                "poi_auto": c["auto"],
                "poi_needs_review": c["needs_review"],
                "poi_resolved": c["resolved"],
                "poi_total": c["auto"] + c["needs_review"] + c["resolved"],
            }
        )
    return out


@router.get("/videos/{video_id}/transcript")
async def get_video_transcript(
    video_id: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """영상의 보정 자막(없으면 원본 자막) 텍스트. RustFS 최신 자산을 읽는다."""
    store = postprocess_service._make_media_store(get_settings())
    text = await media_store.load_latest_asset_text(
        session,
        store,
        video_id=video_id,
        asset_type=AssetType.TRANSCRIPT_CORRECTED.value,
    )
    kind: str | None = "corrected" if text else None
    if not text:
        text = await media_store.load_latest_asset_text(
            session, store, video_id=video_id, asset_type=AssetType.TRANSCRIPT.value
        )
        kind = "raw" if text else None
    return {"text": text, "kind": kind, "video_id": video_id}


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


# --- 테마 중심 POI 공급 (외부 소비자용, X-API-Key) ---


@router.get("/themes")
async def list_themes(
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(
        default=None, max_length=list_pagination.CURSOR_MAX_LENGTH
    ),
    newer_than_id: int | None = Query(
        default=None, ge=0, le=list_pagination.MAX_DB_INTEGER_ID
    ),
    session: AsyncSession = Depends(get_repeatable_read_session),
) -> dict[str, Any]:
    """공급 가능한 테마 목록(유튜버/재생목록/보정 검색어)과 각 테마의 확정 POI 수."""
    try:
        page = await theme_service.list_theme_summaries_page(
            session,
            limit=limit,
            cursor=cursor,
            newer_than_id=newer_than_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return list_pagination.page_payload(page)


@router.get("/themes/places")
async def theme_places(
    kind: str = Query(..., pattern="^(channel|playlist|keyword)$"),
    value: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """테마(유튜버/재생목록/보정 검색어) 하나의 확정 POI 목록.

    `kind`는 `channel`(유튜버)/`playlist`(재생목록)/`keyword`(보정 검색어),
    `value`는 채널 ID/재생목록 ID/검색어 문자열이다.
    """
    return await theme_service.get_theme_places(
        session, kind=kind, value=value  # type: ignore[arg-type]
    )


@router.get("/themes/video/{video_id}/places")
async def video_theme_places(
    video_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """특정 동영상을 테마로 한 확정 POI 목록.

    매치되거나 검수 완료된 POI가 5개 이상일 때에만 `places`를 채워 반환한다
    (미만이면 `sufficient=false` + 빈 목록).
    """
    return await theme_service.get_video_theme_places(session, video_id=video_id)


# --- 관리자 인증/공개 API 키 ---


@router.post("/admin/auth-events", response_model=LoginEventSummary)
async def record_auth_event(
    payload: AuthEventRequest,
    request: Request,
    _actor: str = Depends(require_admin_proxy),
    session: AsyncSession = Depends(get_session),
) -> LoginEventSummary:
    """Next 로그인/로그아웃 라우트가 인증 이벤트를 DB에 남긴다."""
    event = await login_event_service.record(
        session,
        event_type=payload.event_type,
        outcome=payload.outcome,
        attempted_username=payload.attempted_username,
        reason=payload.reason,
        client_ip=payload.client_ip or (request.client.host if request.client else None),
        user_agent=payload.user_agent,
        next_path=payload.next_path,
    )
    return _login_event_payload(event)


@router.get("/admin/login-events", response_model=list[LoginEventSummary])
async def list_login_events(
    limit: int = Query(default=50, ge=1, le=200),
    _actor: str = Depends(require_admin_proxy),
    session: AsyncSession = Depends(get_session),
) -> list[LoginEventSummary]:
    events = await login_event_service.list_recent(session, limit=limit)
    return [_login_event_payload(event) for event in events]


@router.get("/admin/public-api-keys", response_model=list[PublicApiKeySummary])
async def list_public_api_keys(
    limit: int = Query(default=100, ge=1, le=500),
    _actor: str = Depends(require_admin_proxy),
    session: AsyncSession = Depends(get_session),
) -> list[PublicApiKeySummary]:
    keys = await public_api_key_service.list_keys(session, limit=limit)
    return [_public_api_key_payload(item) for item in keys]


@router.post("/admin/public-api-keys", response_model=PublicApiKeyCreateResponse)
async def create_public_api_key(
    payload: PublicApiKeyCreateRequest,
    actor: str = Depends(require_admin_proxy),
    session: AsyncSession = Depends(get_session),
) -> PublicApiKeyCreateResponse:
    api_key, item = await public_api_key_service.create_key(
        session,
        label=payload.label,
        created_by=actor,
        scope=payload.scope,
        commit=False,
    )
    await audit_service.record(
        session,
        actor_type="web",
        action="public_api_key.create",
        target_type="public_api_key",
        target_id=str(item.id),
        payload={"label": item.label, "key_hint": item.key_hint, "scope": item.scope},
    )
    public_api_key_service.invalidate_public_api_key_cache()
    return PublicApiKeyCreateResponse(key=api_key, item=_public_api_key_payload(item))


@router.delete("/admin/public-api-keys/{key_id}", response_model=PublicApiKeySummary)
async def revoke_public_api_key(
    key_id: int,
    actor: str = Depends(require_admin_proxy),
    session: AsyncSession = Depends(get_session),
) -> PublicApiKeySummary:
    item = await public_api_key_service.revoke_key(
        session,
        key_id,
        revoked_by=actor,
        commit=False,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="active public API key not found")
    await audit_service.record(
        session,
        actor_type="web",
        action="public_api_key.revoke",
        target_type="public_api_key",
        target_id=str(item.id),
        payload={"key_hint": item.key_hint, "scope": item.scope},
    )
    public_api_key_service.invalidate_public_api_key_cache()
    return _public_api_key_payload(item)


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


def _login_event_payload(event) -> LoginEventSummary:
    return LoginEventSummary(
        id=event.id,
        event_type=event.event_type,
        outcome=event.outcome,
        attempted_username=event.attempted_username,
        reason=event.reason,
        client_ip=event.client_ip,
        user_agent=event.user_agent,
        next_path=event.next_path,
        created_at=event.created_at,
    )


def _public_api_key_payload(item) -> PublicApiKeySummary:
    return PublicApiKeySummary(
        id=item.id,
        label=item.label,
        key_hint=item.key_hint,
        scope=item.scope,
        state=item.state,
        created_at=item.created_at,
        created_by=item.created_by,
        revoked_at=item.revoked_at,
        revoked_by=item.revoked_by,
    )


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
        "category_code_suggestion": place.category_code_suggestion,
        "sigungu_code": place.sigungu_code,
        "sigungu_name": place.sigungu_name,
        "legal_dong_code": place.legal_dong_code,
        "legal_dong_name": place.legal_dong_name,
        "api_source": place.api_source,
        "is_geocoded": place.is_geocoded,
    }


def _safe_confidence_score(value: Any) -> float | None:
    """외부 JSON에 안전한 0..1 유한 confidence만 반환한다."""
    if value is None or isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(score) or not 0 <= score <= 1:
        return None
    return score


def _candidate_list_payload(item: place_service.CandidateListItem) -> dict[str, Any]:
    """검수 큐 목록용 경량 payload. 리스트 UI가 쓰지 않는 무거운 필드
    (provider_evidence_json·source_text·review_note 등)를 제외하고, 파생값인
    8자리 카테고리 코드는 서버에서 계산해 넣는다(원본 evidence는 보내지 않음)."""
    candidate = item.candidate
    return {
        "id": candidate.id,
        "video_id": candidate.video_id,
        "video_title": item.video_title,
        "channel_title": item.channel_title,
        "ai_place_name": candidate.ai_place_name,
        "location_hint": candidate.location_hint,
        "timestamp_start": candidate.timestamp_start,
        "candidate_category": candidate.candidate_category,
        "candidate_category_code": place_service.candidate_category_code(candidate),
        "match_status": candidate.match_status,
        "confidence_score": _safe_confidence_score(candidate.confidence_score),
        "source_kind": candidate.source_kind,
        "grounding_status": candidate.grounding_status,
        "created_at": candidate.created_at.isoformat(),
        "queue_reason": item.queue_reason.value,
        "is_domestic": candidate.is_domestic,
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
        "candidate_category_code": place_service.candidate_category_code(candidate),
        "match_status": candidate.match_status,
        "matched_place_id": candidate.matched_place_id,
        "confidence_score": _safe_confidence_score(candidate.confidence_score),
        "grounding_status": candidate.grounding_status,
        "is_domestic": candidate.is_domestic,
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

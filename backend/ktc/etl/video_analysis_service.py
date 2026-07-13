"""YouTube URL 기반 Gemini 분석과 transcript 비교 서비스.

T-064는 자막 기반 POI 추출 결과와 별도로 Gemini에 공개 YouTube URL을 직접
전달해 영상 전체를 요약하고, 그 결과를 transcript 후보와 다시 비교한다.
외부 API 호출은 주입 가능한 callable로 분리해 테스트에서 Gemini API 키와
할당량을 쓰지 않도록 한다.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.etl import llm_client
from ktc.models import (
    CrawlRun,
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    MatchStatus,
    VideoAnalysisRunState,
    YoutubeVideo,
    YoutubeVideoAnalysisRun,
)
from ktc.services import feature_export_service, settings_service

# llm 콜러블은 동기(str) 또는 awaitable 반환을 모두 지원한다 — production은
# 게이트웨이(`llm_client`) 경유 async, 테스트 fake는 동기 함수로 주입한다(T-161).
TextLlmCallable = Callable[[str], "str | Awaitable[str]"]
YoutubeUrlLlmCallable = Callable[[str, str], "str | Awaitable[str]"]
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
URL_SUMMARY_PROMPT_VERSION = "t064-url-summary-v1"
RECONCILE_PROMPT_VERSION = "t064-reconcile-v1"


class VideoAnalysisError(RuntimeError):
    """Gemini 영상 분석 생성 또는 파싱에 실패한 경우."""


class AnalysisOwnershipLost(VideoAnalysisError):
    """stale parent attempt의 analysis claim token이 이미 회전한 경우."""

    def __init__(self, result: dict[str, Any]) -> None:
        super().__init__("영상 분석 claim 소유권이 최신 attempt로 이전됨")
        self.result = result


class UrlSummaryPlace(BaseModel):
    """YouTube URL 직접 분석에서 얻은 장소 후보."""

    name: str
    category: str | None = None
    location_hint: str | None = None
    timestamp_start: str | None = None
    timestamp_end: str | None = None
    evidence_text: str | None = None
    visual_evidence: str | None = None
    recommendation_note: str | None = None
    confidence_score: float | None = None


class UrlSummaryResult(BaseModel):
    """YouTube URL 직접 분석 결과."""

    summary: str = ""
    creator_perspective: str | None = None
    places: list[UrlSummaryPlace] = Field(default_factory=list)
    source_notes: list[str] = Field(default_factory=list)
    overall_confidence: float | None = None


class ReconciledPlace(BaseModel):
    """transcript 후보와 URL 분석을 비교한 장소 단위 판단."""

    name: str
    decision: str = "needs_review"
    transcript_candidate_ids: list[int] = Field(default_factory=list)
    transcript_evidence: str | None = None
    url_evidence: str | None = None
    confidence_score: float | None = None
    needs_review_reason: str | None = None


class ReconcileResult(BaseModel):
    """transcript 기반 결과와 URL 분석 결과의 비교·정리 결과."""

    summary: str = ""
    places: list[ReconciledPlace] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    overall_confidence: float | None = None


URL_SUMMARY_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "creator_perspective": {"type": "string"},
        "places": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": "string"},
                    "location_hint": {"type": "string"},
                    "timestamp_start": {"type": "string"},
                    "timestamp_end": {"type": "string"},
                    "evidence_text": {"type": "string"},
                    "visual_evidence": {"type": "string"},
                    "recommendation_note": {"type": "string"},
                    "confidence_score": {"type": "number"},
                },
                "required": ["name"],
            },
        },
        "source_notes": {"type": "array", "items": {"type": "string"}},
        "overall_confidence": {"type": "number"},
    },
    "required": ["summary", "places"],
}

RECONCILE_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "places": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "decision": {"type": "string"},
                    "transcript_candidate_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "transcript_evidence": {"type": "string"},
                    "url_evidence": {"type": "string"},
                    "confidence_score": {"type": "number"},
                    "needs_review_reason": {"type": "string"},
                },
                "required": ["name", "decision"],
            },
        },
        "conflicts": {"type": "array", "items": {"type": "string"}},
        "overall_confidence": {"type": "number"},
    },
    "required": ["summary", "places"],
}


def _compact(value: str | None) -> str:
    return " ".join(value.split()) if value else ""


def _confidence(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return None


def _video_url(video: YoutubeVideo) -> str:
    url = _compact(video.canonical_url) or _compact(video.url)
    if not url:
        raise VideoAnalysisError("YouTube URL이 비어 있다")
    return url


def _reconcile_prompt_input_snapshot(video: YoutubeVideo) -> str:
    """reconcile prompt에 들어가는 영상 입력만 canonical 문자열로 고정한다."""
    return json.dumps(
        {
            "video": _video_context(video),
            "transcript_summary": video.transcript_summary,
            "description_gemini_corrected": video.description_gemini_corrected,
            "gemini_url_summary_json": video.gemini_url_summary_json,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _reconcile_canonical_output_snapshot(video: YoutubeVideo) -> str:
    """다른 reconcile 실행이 먼저 확정한 canonical 결과를 식별한다."""
    return json.dumps(
        {
            "reconciled_summary": video.reconciled_summary,
            "reconciled_summary_json": video.reconciled_summary_json,
            "reconciled_summary_at": video.reconciled_summary_at,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _url_prompt_input_snapshot(video: YoutubeVideo) -> str:
    """URL 분석 prompt에 들어가는 영상 입력만 canonical 문자열로 고정한다."""
    return json.dumps(
        {"video": _video_context(video)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _url_canonical_output_snapshot(video: YoutubeVideo) -> str:
    """다른 URL 분석이 먼저 확정한 canonical 결과를 식별한다."""
    return json.dumps(
        {
            "gemini_url_summary": video.gemini_url_summary,
            "gemini_url_summary_json": video.gemini_url_summary_json,
            "gemini_url_summary_at": video.gemini_url_summary_at,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _video_context(video: YoutubeVideo) -> dict[str, Any]:
    return {
        "video_id": video.video_id,
        "title": video.title,
        "url": video.canonical_url or video.url,
        "channel_id": video.channel_id,
        "channel_name": video.channel_name,
        "published_at": video.published_at.isoformat() if video.published_at else None,
        "duration_seconds": video.duration_seconds,
        "default_language": video.default_language,
        "tags": video.tags_json or [],
        "description_raw": video.description_raw,
        "description_gemini_corrected": video.description_gemini_corrected,
    }


def build_url_summary_prompt(video: YoutubeVideo) -> str:
    """Gemini YouTube URL 직접 분석 프롬프트를 구성한다."""
    return (
        "공개 YouTube 여행 영상을 분석해 한국어 여행 계획에 쓸 수 있는 정보를 "
        "정리하라. 영상의 화면, 음성, 설명란 맥락을 함께 보고 방문 장소와 근거를 "
        "분리해 적어라. 확실하지 않은 장소명·위치·카테고리는 단정하지 말고 "
        "source_notes에 불확실성을 남겨라. 반드시 주어진 JSON Schema에 맞는 "
        "JSON만 출력하라.\n\n"
        "[영상 메타데이터]\n"
        f"{json.dumps(_video_context(video), ensure_ascii=False)}\n\n"
        "[필수 기준]\n"
        "- summary: 영상 전체 내용을 3~6문장으로 요약\n"
        "- creator_perspective: 유튜버가 추천하거나 강조한 관점\n"
        "- places: 장소명, 카테고리, 위치 힌트, timestamp, 음성/자막 근거, 화면 근거, "
        "추천 포인트, 신뢰도(0~1)\n"
        "- source_notes: URL 접근 제한, 공개 영상 여부, 낮은 신뢰도, 화면만으로 "
        "판단한 내용 등 주의점\n"
    )


def build_reconcile_prompt(
    *,
    video: YoutubeVideo,
    transcript_candidates: list[dict[str, Any]],
    url_summary: dict[str, Any],
) -> str:
    """transcript 후보와 URL summary 비교 프롬프트를 구성한다."""
    transcript_context = {
        "transcript_summary": video.transcript_summary,
        "description_gemini_corrected": video.description_gemini_corrected,
        "candidates": transcript_candidates,
    }
    return (
        "다음은 같은 YouTube 여행 영상에서 나온 두 결과다. 하나는 자막 기반 장소 "
        "후보이고, 다른 하나는 Gemini가 YouTube URL을 직접 분석한 요약이다. "
        "두 결과를 비교해 장소 후보를 정리하라. 이름·주소 힌트·timestamp·카테고리·"
        "근거가 충돌하거나 신뢰도가 낮으면 자동 확정하지 말고 decision을 "
        "`needs_review` 또는 `conflict`로 둔다. 사람이 검수할 이유는 "
        "needs_review_reason에 한국어로 남긴다. 반드시 주어진 JSON Schema에 "
        "맞는 JSON만 출력하라.\n\n"
        f"[영상 메타데이터]\n{json.dumps(_video_context(video), ensure_ascii=False)}\n\n"
        "[자막 기반 결과]\n"
        f"{json.dumps(transcript_context, ensure_ascii=False)}\n\n"
        "[YouTube URL 직접 분석 결과]\n"
        f"{json.dumps(url_summary, ensure_ascii=False)}\n"
    )


def parse_url_summary(payload: str) -> UrlSummaryResult:
    """URL summary JSON 문자열을 파싱·검증한다."""
    try:
        data = json.loads(payload)
        result = UrlSummaryResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise VideoAnalysisError(f"URL summary 결과 파싱 실패: {exc}") from exc
    if not result.summary.strip():
        raise VideoAnalysisError("URL summary가 비어 있다")
    return result


def parse_reconcile(payload: str) -> ReconcileResult:
    """reconcile JSON 문자열을 파싱·검증한다."""
    try:
        data = json.loads(payload)
        result = ReconcileResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise VideoAnalysisError(f"reconcile 결과 파싱 실패: {exc}") from exc
    if not result.summary.strip():
        raise VideoAnalysisError("reconcile summary가 비어 있다")
    return result


def make_youtube_url_llm(
    runtime: llm_client.LlmRuntime,
    *,
    timeout_seconds: float = 120.0,
) -> YoutubeUrlLlmCallable:
    """공개 YouTube URL을 `file_data.file_uri`로 Gemini에 직접 전달한다(Gemini 전용).

    게이트웨이의 멀티모달 진입점(`llm_client.generate_multimodal`)을 경유한다 —
    사용자 사전 프롬프트 prepend·rate limiter 예약·thread 격리는 게이트웨이가
    처리한다(T-161).
    """

    async def call(prompt: str, video_url: str) -> str:
        try:
            return await llm_client.generate_multimodal(
                runtime,
                [
                    {"file_data": {"file_uri": video_url}},
                    {"text": prompt},
                ],
                response_schema=URL_SUMMARY_RESPONSE_JSON_SCHEMA,
                timeout_seconds=timeout_seconds,
            )
        except llm_client.LlmRequestError as exc:
            # 원인 메시지를 포함해 run 실패 기록(last_error)만으로 사유를 진단할 수 있게 한다
            # (예: "Gemini 응답에 candidates가 없다").
            raise VideoAnalysisError(
                "Gemini YouTube URL summary 호출 실패"
                f"(status={exc.status_code}, model={runtime.model}): {exc}"
            ) from exc

    return call


def make_gemini_youtube_url_llm(
    *,
    api_key: str | None = None,
    model: str | None = None,
    timeout_seconds: float = 120.0,
) -> YoutubeUrlLlmCallable:
    """`.env`/인자 기반 YouTube URL caller (BACK-COMPAT shim → make_youtube_url_llm)."""
    from dataclasses import replace

    runtime = llm_client.LlmRuntime.from_settings(model=model)
    if api_key:
        runtime = replace(runtime, gemini_api_key=api_key)
    if not runtime.gemini_api_key:
        raise ValueError("GEMINI_API_KEY가 필요하다")
    return make_youtube_url_llm(runtime, timeout_seconds=timeout_seconds)


def make_text_llm(
    runtime: llm_client.LlmRuntime,
    *,
    response_schema: dict[str, Any] | None = None,
) -> TextLlmCallable:
    """선택된 엔진(Gemini/DeepSeek) + 사전 프롬프트로 reconcile text `LlmCallable`을 만든다."""
    schema = response_schema or RECONCILE_RESPONSE_JSON_SCHEMA

    async def call(prompt: str) -> str:
        try:
            return await llm_client.complete_json(runtime, prompt, response_schema=schema)
        except llm_client.LlmRequestError as exc:
            # 원인 메시지 포함 — run 실패 기록만으로 사유 진단(위 URL summary와 동일).
            raise VideoAnalysisError(
                f"reconcile 호출 실패(status={exc.status_code}, model={runtime.model}): {exc}"
            ) from exc

    return call


def make_gemini_text_llm(
    *,
    api_key: str | None = None,
    model: str | None = None,
    response_schema: dict[str, Any] | None = None,
    timeout_seconds: float = 90.0,
) -> TextLlmCallable:
    """`.env`/인자 기반 text-only caller (BACK-COMPAT shim → make_text_llm)."""
    from dataclasses import replace

    runtime = llm_client.LlmRuntime.from_settings(model=model)
    if api_key:
        runtime = replace(runtime, gemini_api_key=api_key)
    if not (runtime.gemini_api_key or runtime.is_deepseek):
        raise ValueError("GEMINI_API_KEY가 필요하다")
    return make_text_llm(runtime, response_schema=response_schema)


async def _mark_running(
    session: AsyncSession,
    analysis_run: YoutubeVideoAnalysisRun,
    *,
    model: str,
    prompt_version: str,
    claim_token: str,
    owner_crawl_run_id: int | None,
    owner_retry_count: int | None,
) -> YoutubeVideoAnalysisRun:
    if not await _lock_current_owner_parent(
        session,
        owner_crawl_run_id=owner_crawl_run_id,
        owner_retry_count=owner_retry_count,
    ):
        current = (
            await session.execute(
                select(YoutubeVideoAnalysisRun)
                .where(YoutubeVideoAnalysisRun.id == analysis_run.id)
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).scalar_one()
        lost_result = _ownership_lost_result(current)
        await session.rollback()
        raise AnalysisOwnershipLost(lost_result)
    current = (
        await session.execute(
            select(YoutubeVideoAnalysisRun)
            .where(YoutubeVideoAnalysisRun.id == analysis_run.id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one()
    if current.claim_token != claim_token:
        lost_result = _ownership_lost_result(current)
        await session.rollback()
        raise AnalysisOwnershipLost(lost_result)
    current.state = VideoAnalysisRunState.RUNNING
    current.model = model
    current.prompt_version = prompt_version
    current.started_at = datetime.now(timezone.utc)
    current.finished_at = None
    current.last_error = None
    await session.commit()
    await session.refresh(current)
    return current


async def _ensure_claim_token(
    session: AsyncSession,
    analysis_run: YoutubeVideoAnalysisRun,
) -> str:
    """scheduler 밖 직접 service 호출에도 원자적인 ad-hoc claim token을 발급한다."""
    if analysis_run.claim_token:
        return str(analysis_run.claim_token)
    token = str(uuid4())
    claimed = await session.scalar(
        update(YoutubeVideoAnalysisRun)
        .where(
            YoutubeVideoAnalysisRun.id == analysis_run.id,
            YoutubeVideoAnalysisRun.claim_token.is_(None),
            YoutubeVideoAnalysisRun.state.in_(
                [
                    VideoAnalysisRunState.PENDING,
                    VideoAnalysisRunState.RUNNING,
                ]
            ),
        )
        .values(claim_token=token)
        .returning(YoutubeVideoAnalysisRun.id)
    )
    if claimed is None:
        await session.rollback()
        current = (
            await session.execute(
                select(YoutubeVideoAnalysisRun).where(
                    YoutubeVideoAnalysisRun.id == analysis_run.id
                )
            )
        ).scalar_one()
        lost_result = _ownership_lost_result(current)
        await session.rollback()
        raise AnalysisOwnershipLost(lost_result)
    await session.commit()
    await session.refresh(analysis_run)
    return token


async def _mark_failed(
    session: AsyncSession,
    analysis_run: YoutubeVideoAnalysisRun,
    exc: Exception,
    *,
    claim_token: str,
    owner_crawl_run_id: int | None,
    owner_retry_count: int | None,
) -> dict[str, Any]:
    # LLM 대기 중 parent attempt가 재투입돼 token이 회전했으면 이전 owner는 최신 row를
    # FAILED로 바꿀 권한이 없다.
    await session.rollback()
    parent_owned = await _lock_current_owner_parent(
        session,
        owner_crawl_run_id=owner_crawl_run_id,
        owner_retry_count=owner_retry_count,
    )
    current = (
        await session.execute(
            select(YoutubeVideoAnalysisRun)
            .where(YoutubeVideoAnalysisRun.id == analysis_run.id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one()
    if not parent_owned or current.claim_token != claim_token:
        lost_result = _ownership_lost_result(current)
        await session.rollback()
        return lost_result
    current.state = VideoAnalysisRunState.FAILED
    current.finished_at = datetime.now(timezone.utc)
    current.last_error = str(exc)
    current.owner_crawl_run_id = None
    current.owner_retry_count = None
    current.claim_token = None
    await session.commit()
    return {
        "analysis_run_id": current.id,
        "run_type": current.run_type,
        "state": VideoAnalysisRunState.FAILED.value,
        "error": str(exc),
    }


def _ownership_lost_result(
    analysis_run: YoutubeVideoAnalysisRun,
) -> dict[str, Any]:
    """회전된 claim의 최신 상태를 변경하지 않고 이전 owner 종료를 알린다."""
    state = (
        analysis_run.state.value
        if isinstance(analysis_run.state, VideoAnalysisRunState)
        else str(analysis_run.state)
    )
    return {
        "analysis_run_id": analysis_run.id,
        "run_type": analysis_run.run_type,
        "state": state,
        "stale_input": False,
        "superseded": True,
        "ownership_lost": True,
    }


async def _lock_current_owner_parent(
    session: AsyncSession,
    *,
    owner_crawl_run_id: int | None,
    owner_retry_count: int | None,
) -> bool:
    """scheduler owner의 parent generation을 잠가 apply까지 재투입을 직렬화한다."""
    if owner_crawl_run_id is None:
        return True
    parent = (
        await session.execute(
            select(CrawlRun)
            .where(CrawlRun.id == owner_crawl_run_id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one_or_none()
    return (
        parent is not None
        and parent.state == "running"
        and parent.retry_count == owner_retry_count
    )


async def _lock_owned_analysis_run(
    session: AsyncSession,
    *,
    analysis_run_id: int,
    claim_token: str,
    owner_crawl_run_id: int | None,
    owner_retry_count: int | None,
) -> YoutubeVideoAnalysisRun | None:
    """analysis row를 잠그고 현재 claim token 소유자일 때만 반환한다."""
    if not await _lock_current_owner_parent(
        session,
        owner_crawl_run_id=owner_crawl_run_id,
        owner_retry_count=owner_retry_count,
    ):
        return None
    current = (
        await session.execute(
            select(YoutubeVideoAnalysisRun)
            .where(YoutubeVideoAnalysisRun.id == analysis_run_id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one()
    return current if current.claim_token == claim_token else None


async def run_url_summary_analysis(
    session: AsyncSession,
    video: YoutubeVideo,
    analysis_run: YoutubeVideoAnalysisRun,
    *,
    llm: YoutubeUrlLlmCallable | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """`url_summary` analysis run을 실행하고 DB에 저장한다."""
    runtime = await settings_service.get_llm_runtime(session)
    if model:
        runtime = replace(runtime, model=model)
    resolved_model = runtime.model
    claim_token = ""
    owner_crawl_run_id = analysis_run.owner_crawl_run_id
    owner_retry_count = analysis_run.owner_retry_count
    try:
        claim_token = await _ensure_claim_token(session, analysis_run)
        analysis_run = await _mark_running(
            session,
            analysis_run,
            model=resolved_model,
            prompt_version=URL_SUMMARY_PROMPT_VERSION,
            claim_token=claim_token,
            owner_crawl_run_id=owner_crawl_run_id,
            owner_retry_count=owner_retry_count,
        )
        video = (
            await session.execute(
                select(YoutubeVideo)
                .where(YoutubeVideo.video_id == video.video_id)
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).scalar_one()
        prompt_input_snapshot = _url_prompt_input_snapshot(video)
        canonical_output_snapshot = _url_canonical_output_snapshot(video)
        request_prompt = build_url_summary_prompt(video)
        request_url = _video_url(video)
        # 영상 SELECT transaction과 connection을 외부 Gemini 대기 전에 반환한다.
        await session.commit()
        resolved_llm = llm or make_youtube_url_llm(runtime)
        # thread 격리·rate limiter 예약은 게이트웨이(`llm_client`)가 처리한다(T-161).
        raw_result = await llm_client.maybe_await(
            resolved_llm(request_prompt, request_url)
        )
        result = parse_url_summary(raw_result)
    except AnalysisOwnershipLost as exc:
        return exc.result
    except Exception as exc:
        return await _mark_failed(
            session,
            analysis_run,
            exc,
            claim_token=claim_token,
            owner_crawl_run_id=owner_crawl_run_id,
            owner_retry_count=owner_retry_count,
        )

    result_json = result.model_dump(mode="json")
    score = _confidence(result.overall_confidence)
    now = datetime.now(timezone.utc)
    # LLM 대기 뒤 export writer lock을 먼저 잡고 영상 최신 행을 잠근다. URL summary가
    # effective video_summary를 바꾸면 같은 영상의 export 후보 전부를 dirty로 재등록한다.
    await feature_export_service.acquire_feature_export_lock(session)
    owned_analysis_run = await _lock_owned_analysis_run(
        session,
        analysis_run_id=analysis_run.id,
        claim_token=claim_token,
        owner_crawl_run_id=owner_crawl_run_id,
        owner_retry_count=owner_retry_count,
    )
    if owned_analysis_run is None:
        current = (
            await session.execute(
                select(YoutubeVideoAnalysisRun)
                .where(YoutubeVideoAnalysisRun.id == analysis_run.id)
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).scalar_one()
        lost_result = _ownership_lost_result(current)
        await session.rollback()
        return lost_result
    analysis_run = owned_analysis_run
    video = (
        await session.execute(
            select(YoutubeVideo)
            .where(YoutubeVideo.video_id == video.video_id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one()
    superseded = (
        _url_canonical_output_snapshot(video) != canonical_output_snapshot
    )
    stale_input = (
        not superseded
        and _url_prompt_input_snapshot(video) != prompt_input_snapshot
    )
    previous_export_summary = feature_export_service.export_video_summary(video)
    analysis_run.summary_json = result_json
    analysis_run.summary_text = result.summary
    analysis_run.confidence_score = score
    if not stale_input and not superseded:
        analysis_run.state = VideoAnalysisRunState.DONE
        analysis_run.finished_at = now
        analysis_run.owner_crawl_run_id = None
        analysis_run.owner_retry_count = None
        analysis_run.claim_token = None
        video.gemini_url_summary = result.summary
        video.gemini_url_summary_json = result_json
        video.gemini_url_summary_model = resolved_model
        video.gemini_url_summary_at = now
    if (
        not stale_input
        and not superseded
        and feature_export_service.export_video_summary(video)
        != previous_export_summary
    ):
        await feature_export_service.mark_video_candidates_dirty(
            session,
            video.video_id,
            reason="video_url_summary",
        )
    if stale_input:
        # 정상 동시 변경은 실패가 아니라 현재 worker가 즉시 재실행할 입력 drift다.
        # running 소유권을 유지해야 stale commit과 다음 시도 사이에 다른 handler가 같은
        # row를 claim해 LLM을 중복 호출하지 않는다. worker가 중단되면 lease 회수가 같은
        # row를 pending으로 되돌린다.
        analysis_run.state = VideoAnalysisRunState.RUNNING
        analysis_run.finished_at = None
        analysis_run.last_error = "stale_input: URL 분석 중 영상 입력이 변경됨"
    elif superseded:
        analysis_run.state = VideoAnalysisRunState.FAILED
        analysis_run.finished_at = now
        analysis_run.last_error = (
            "superseded_by_concurrent_result: 다른 URL 분석 결과가 먼저 확정됨"
        )
        analysis_run.owner_crawl_run_id = None
        analysis_run.owner_retry_count = None
        analysis_run.claim_token = None
    await session.commit()
    return {
        "analysis_run_id": analysis_run.id,
        "run_type": analysis_run.run_type,
        "state": (
            VideoAnalysisRunState.RUNNING.value
            if stale_input
            else (
                VideoAnalysisRunState.FAILED.value
                if superseded
                else VideoAnalysisRunState.DONE.value
            )
        ),
        "stale_input": stale_input,
        "superseded": superseded,
        "places": len(result.places),
        "confidence_score": score,
    }


async def transcript_candidates_for_video(
    session: AsyncSession,
    video_id: str,
) -> list[ExtractedPlaceCandidate]:
    """영상의 transcript 기반 장소 후보를 id 순서로 조회한다.

    soft delete된 후보는 reconcile 비교 대상에서 제외한다(T-160).
    """
    result = await session.execute(
        select(ExtractedPlaceCandidate)
        .where(
            ExtractedPlaceCandidate.video_id == video_id,
            ExtractedPlaceCandidate.deleted_at.is_(None),
        )
        .order_by(ExtractedPlaceCandidate.id)
    )
    return list(result.scalars().all())


def _candidate_context(candidate: ExtractedPlaceCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.id,
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
        "reviewed_by": candidate.reviewed_by,
        "reviewed_at": (
            candidate.reviewed_at.isoformat() if candidate.reviewed_at else None
        ),
        "review_note": candidate.review_note,
        "audit_status": candidate.audit_status,
        "audit_reviewed_by": candidate.audit_reviewed_by,
        "audit_reviewed_at": (
            candidate.audit_reviewed_at.isoformat()
            if candidate.audit_reviewed_at
            else None
        ),
        "audit_note": candidate.audit_note,
    }


def _review_decision(place: ReconciledPlace) -> bool:
    decision = place.decision.strip().lower()
    score = _confidence(place.confidence_score)
    return (
        decision in {"needs_review", "conflict", "low_confidence", "uncertain"}
        or bool(_compact(place.needs_review_reason))
        or (score is not None and score < 0.65)
    )


def _apply_reconcile_review_notes(
    *,
    candidates: list[ExtractedPlaceCandidate],
    snapshot_revisions: dict[int, int],
    result: ReconcileResult,
    analysis_run_id: int,
) -> set[int]:
    by_id = {candidate.id: candidate for candidate in candidates}
    updated_candidate_ids: set[int] = set()
    processed_candidate_ids: set[int] = set()
    for place in result.places:
        if not _review_decision(place):
            continue
        note = _compact(place.needs_review_reason) or "Gemini URL 분석과 자막 기반 후보가 완전히 일치하지 않는다."
        for candidate_id in place.transcript_candidate_ids:
            candidate = by_id.get(candidate_id)
            if candidate is None or candidate.id in processed_candidate_ids:
                continue
            # LLM 입력 뒤 사람 또는 다른 worker가 후보를 변경했다면 결과를 적용하지 않는다.
            # DB trigger가 모든 UPDATE에서 revision을 올리므로 needs→ignore→reopen ABA와
            # evidence-only 변경도 같은 fence로 감지된다. 사람 확정/제외와 soft delete는
            # revision이 우연히 같아도 상태 gate에서 다시 차단한다.
            if (
                candidate.state_revision != snapshot_revisions.get(candidate.id)
                or candidate.deleted_at is not None
                or candidate.match_status
                not in {
                    MatchStatus.NEEDS_REVIEW.value,
                    MatchStatus.MATCHED.value,
                }
            ):
                continue
            processed_candidate_ids.add(candidate.id)
            candidate.provider_evidence_json = _merge_provider_evidence(
                candidate.provider_evidence_json,
                reconcile={
                    "analysis_run_id": analysis_run_id,
                    "name": place.name,
                    "decision": place.decision,
                    "transcript_evidence": place.transcript_evidence,
                    "url_evidence": place.url_evidence,
                    "confidence_score": place.confidence_score,
                    "needs_review_reason": place.needs_review_reason,
                    "conflicts": result.conflicts,
                },
            )
            # `review_candidate`는 NEEDS_REVIEW 상태를 유지한 채 사람 메모를 남긴다.
            # audit 표본도 별도 사람 검수 lifecycle을 가진다. 두 경우 AI 의견은 근거에만
            # 보존하고 사람 상태·note·audit 판정을 덮지 않는다.
            human_review_protected = (
                candidate.match_status == MatchStatus.NEEDS_REVIEW.value
                and (
                    candidate.reviewed_by is not None
                    or candidate.reviewed_at is not None
                )
            )
            audit_protected = (
                candidate.audit_status is not None
                or candidate.audit_reviewed_by is not None
                or candidate.audit_reviewed_at is not None
            )
            if human_review_protected or audit_protected:
                continue
            candidate.match_status = MatchStatus.NEEDS_REVIEW
            candidate.review_note = note
            candidate.analysis_run_id = analysis_run_id
            candidate.feature_export_status = FeatureExportStatus.PENDING.value
            updated_candidate_ids.add(candidate.id)
    return updated_candidate_ids


async def _lock_reconcile_candidates_for_apply(
    session: AsyncSession,
    *,
    video_id: str,
) -> list[ExtractedPlaceCandidate]:
    """prompt에 영향을 주는 현재 활성 후보 전체를 고정 순서로 잠근다."""
    rows = await session.execute(
        select(ExtractedPlaceCandidate)
        .where(
            ExtractedPlaceCandidate.video_id == video_id,
            ExtractedPlaceCandidate.deleted_at.is_(None),
        )
        .order_by(ExtractedPlaceCandidate.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True, autoflush=False)
    )
    return list(rows.scalars().all())


async def run_reconcile_analysis(
    session: AsyncSession,
    video: YoutubeVideo,
    analysis_run: YoutubeVideoAnalysisRun,
    *,
    llm: TextLlmCallable | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """`reconcile` analysis run을 실행하고 DB에 저장한다."""
    runtime = await settings_service.get_llm_runtime(session)
    if model:
        runtime = replace(runtime, model=model)
    resolved_model = runtime.model
    claim_token = ""
    owner_crawl_run_id = analysis_run.owner_crawl_run_id
    owner_retry_count = analysis_run.owner_retry_count
    try:
        claim_token = await _ensure_claim_token(session, analysis_run)
        analysis_run = await _mark_running(
            session,
            analysis_run,
            model=resolved_model,
            prompt_version=RECONCILE_PROMPT_VERSION,
            claim_token=claim_token,
            owner_crawl_run_id=owner_crawl_run_id,
            owner_retry_count=owner_retry_count,
        )
        # 호출자가 오래 보유한 ORM 객체가 아니라 prompt를 만들 transaction의 최신 영상
        # snapshot을 사용한다. 이후 어떤 입력이 바뀌어도 apply 단계 fingerprint가 거부한다.
        video = (
            await session.execute(
                select(YoutubeVideo)
                .where(YoutubeVideo.video_id == video.video_id)
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).scalar_one()
        if not video.gemini_url_summary_json:
            raise VideoAnalysisError("reconcile 실행 전 url_summary 결과가 필요하다")
        candidates = await transcript_candidates_for_video(session, video.video_id)
        candidate_revisions = {
            candidate.id: candidate.state_revision for candidate in candidates
        }
        prompt_input_snapshot = _reconcile_prompt_input_snapshot(video)
        canonical_output_snapshot = _reconcile_canonical_output_snapshot(video)
        prompt = build_reconcile_prompt(
            video=video,
            transcript_candidates=[_candidate_context(item) for item in candidates],
            url_summary=video.gemini_url_summary_json,
        )
        # prompt는 여기서 완성된 immutable 문자열이다. 후보 SELECT가 연 read transaction을
        # 외부 LLM 대기 전에 끝내야 결과 적용 시 READ COMMITTED 최신 snapshot을 얻는다.
        await session.commit()
        resolved_llm = llm or make_text_llm(runtime)
        # thread 격리·rate limiter 예약은 게이트웨이(`llm_client`)가 처리한다(T-161).
        raw_result = await llm_client.maybe_await(resolved_llm(prompt))
        result = parse_reconcile(raw_result)
    except AnalysisOwnershipLost as exc:
        return exc.result
    except Exception as exc:
        return await _mark_failed(
            session,
            analysis_run,
            exc,
            claim_token=claim_token,
            owner_crawl_run_id=owner_crawl_run_id,
            owner_retry_count=owner_retry_count,
        )

    result_json = result.model_dump(mode="json")
    score = _confidence(result.overall_confidence)
    now = datetime.now(timezone.utc)
    # LLM 반환을 적용하기 전 export lock을 candidate row보다 먼저 잡는다. 이 임계구간에
    # 상태 강등 dirty와 영상 summary dirty를 함께 기록해 공급 GET이 중간 snapshot을 만들지
    # 못하게 한다.
    await feature_export_service.acquire_feature_export_lock(session)
    owned_analysis_run = await _lock_owned_analysis_run(
        session,
        analysis_run_id=analysis_run.id,
        claim_token=claim_token,
        owner_crawl_run_id=owner_crawl_run_id,
        owner_retry_count=owner_retry_count,
    )
    if owned_analysis_run is None:
        current = (
            await session.execute(
                select(YoutubeVideoAnalysisRun)
                .where(YoutubeVideoAnalysisRun.id == analysis_run.id)
                .with_for_update()
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).scalar_one()
        lost_result = _ownership_lost_result(current)
        await session.rollback()
        return lost_result
    analysis_run = owned_analysis_run
    current_candidates = await _lock_reconcile_candidates_for_apply(
        session,
        video_id=video.video_id,
    )
    video = (
        await session.execute(
            select(YoutubeVideo)
            .where(YoutubeVideo.video_id == video.video_id)
            .with_for_update()
            .execution_options(populate_existing=True, autoflush=False)
        )
    ).scalar_one()
    current_revisions = {
        candidate.id: candidate.state_revision for candidate in current_candidates
    }
    superseded = (
        _reconcile_canonical_output_snapshot(video) != canonical_output_snapshot
    )
    stale_input = (
        not superseded
        and (
            current_revisions != candidate_revisions
            or _reconcile_prompt_input_snapshot(video) != prompt_input_snapshot
        )
    )
    updated_candidate_ids: set[int] = set()
    if not stale_input and not superseded:
        updated_candidate_ids = _apply_reconcile_review_notes(
            candidates=current_candidates,
            snapshot_revisions=candidate_revisions,
            result=result,
            analysis_run_id=analysis_run.id,
        )
    previous_export_summary = feature_export_service.export_video_summary(video)
    analysis_run.summary_json = result_json
    analysis_run.summary_text = result.summary
    analysis_run.confidence_score = score
    if not stale_input and not superseded:
        analysis_run.state = VideoAnalysisRunState.DONE
        analysis_run.finished_at = now
        analysis_run.owner_crawl_run_id = None
        analysis_run.owner_retry_count = None
        analysis_run.claim_token = None
        video.reconciled_summary = result.summary
        video.reconciled_summary_json = result_json
        video.reconciled_summary_at = now
    if (
        not stale_input
        and not superseded
        and feature_export_service.export_video_summary(video)
        != previous_export_summary
    ):
        # summary는 같은 영상의 참조되지 않은 후보 payload에도 복제된다.
        await feature_export_service.mark_video_candidates_dirty(
            session,
            video.video_id,
            reason="video_reconcile_summary",
        )
    elif updated_candidate_ids:
        await feature_export_service.mark_candidates_dirty(
            session,
            sorted(updated_candidate_ids),
            reason="video_reconcile_review",
        )
    if stale_input:
        # URL 분석과 같은 lease 소유권 규칙을 사용한다. 즉시 bounded retry 동안 다른
        # handler의 중복 claim을 차단하고, 프로세스 중단만 lease 회수 대상으로 남긴다.
        analysis_run.state = VideoAnalysisRunState.RUNNING
        analysis_run.finished_at = None
        analysis_run.last_error = "stale_input: reconcile 입력 후보 또는 영상이 변경됨"
    elif superseded:
        analysis_run.state = VideoAnalysisRunState.FAILED
        analysis_run.finished_at = now
        analysis_run.last_error = (
            "superseded_by_concurrent_result: 다른 reconcile 결과가 먼저 확정됨"
        )
        analysis_run.owner_crawl_run_id = None
        analysis_run.owner_retry_count = None
        analysis_run.claim_token = None
    await session.commit()
    return {
        "analysis_run_id": analysis_run.id,
        "run_type": analysis_run.run_type,
        "state": (
            VideoAnalysisRunState.RUNNING.value
            if stale_input
            else (
                VideoAnalysisRunState.FAILED.value
                if superseded
                else VideoAnalysisRunState.DONE.value
            )
        ),
        "places": len(result.places),
        "conflicts": len(result.conflicts),
        "updated_review_candidates": len(updated_candidate_ids),
        "stale_input": stale_input,
        "superseded": superseded,
        "confidence_score": score,
    }


def _merge_provider_evidence(
    existing: dict[str, Any] | None,
    *,
    reconcile: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing or {})
    merged["reconcile"] = reconcile
    return merged

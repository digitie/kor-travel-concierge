"""YouTube URL 기반 Gemini 분석과 transcript 비교 서비스.

T-064는 자막 기반 POI 추출 결과와 별도로 Gemini에 공개 YouTube URL을 직접
전달해 영상 전체를 요약하고, 그 결과를 transcript 후보와 다시 비교한다.
외부 API 호출은 주입 가능한 callable로 분리해 테스트에서 Gemini API 키와
할당량을 쓰지 않도록 한다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.etl import llm_client
from ktc.etl.gemini_client import GeminiRequestError, post_generate_content
from ktc.models import (
    ExtractedPlaceCandidate,
    FeatureExportStatus,
    MatchStatus,
    VideoAnalysisRunState,
    YoutubeVideo,
    YoutubeVideoAnalysisRun,
)
from ktc.services import settings_service

TextLlmCallable = Callable[[str], str]
YoutubeUrlLlmCallable = Callable[[str, str], str]
GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
URL_SUMMARY_PROMPT_VERSION = "t064-url-summary-v1"
RECONCILE_PROMPT_VERSION = "t064-reconcile-v1"


class VideoAnalysisError(RuntimeError):
    """Gemini 영상 분석 생성 또는 파싱에 실패한 경우."""


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

    이 경로는 디스패처(`llm_client.complete_json`)를 쓰지 않지만, 사용자 사전 프롬프트는
    동일하게 prepend한다(`runtime.preprompt`).
    """

    def call(prompt: str, video_url: str) -> str:
        full = llm_client.compose_prompt(runtime.preprompt, prompt)
        try:
            data = post_generate_content(
                api_key=runtime.gemini_api_key,
                model=runtime.model,
                body={
                    "contents": [
                        {
                            "parts": [
                                {"file_data": {"file_uri": video_url}},
                                {"text": full},
                            ]
                        }
                    ],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseSchema": URL_SUMMARY_RESPONSE_JSON_SCHEMA,
                    },
                },
                timeout_seconds=timeout_seconds,
            )
        except GeminiRequestError as exc:
            raise VideoAnalysisError(
                "Gemini YouTube URL summary 호출 실패"
                f"(status={exc.status_code}, model={runtime.model})"
            ) from exc
        return _extract_gemini_text(data)

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

    def call(prompt: str) -> str:
        try:
            return llm_client.complete_json(runtime, prompt, response_schema=schema)
        except llm_client.LlmRequestError as exc:
            raise VideoAnalysisError(
                f"reconcile 호출 실패(status={exc.status_code}, model={runtime.model})"
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


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise VideoAnalysisError("Gemini 응답에 candidates가 없다")
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise VideoAnalysisError("Gemini 응답에 content.parts가 없다")
    texts = [
        part.get("text")
        for part in parts
        if isinstance(part, dict) and part.get("text")
    ]
    if not texts:
        raise VideoAnalysisError("Gemini 응답 text가 비어 있다")
    return "\n".join(str(text) for text in texts)


async def _mark_running(
    session: AsyncSession,
    analysis_run: YoutubeVideoAnalysisRun,
    *,
    model: str,
    prompt_version: str,
) -> None:
    analysis_run.state = VideoAnalysisRunState.RUNNING
    analysis_run.model = model
    analysis_run.prompt_version = prompt_version
    analysis_run.started_at = datetime.now(timezone.utc)
    analysis_run.finished_at = None
    analysis_run.last_error = None
    await session.commit()
    await session.refresh(analysis_run)


async def _mark_failed(
    session: AsyncSession,
    analysis_run: YoutubeVideoAnalysisRun,
    exc: Exception,
) -> dict[str, Any]:
    analysis_run.state = VideoAnalysisRunState.FAILED
    analysis_run.finished_at = datetime.now(timezone.utc)
    analysis_run.last_error = str(exc)
    await session.commit()
    return {
        "analysis_run_id": analysis_run.id,
        "run_type": analysis_run.run_type,
        "state": VideoAnalysisRunState.FAILED.value,
        "error": str(exc),
    }


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
    try:
        await _mark_running(
            session,
            analysis_run,
            model=resolved_model,
            prompt_version=URL_SUMMARY_PROMPT_VERSION,
        )
        resolved_llm = llm or make_youtube_url_llm(runtime)
        raw_result = await asyncio.to_thread(
            resolved_llm,
            build_url_summary_prompt(video),
            _video_url(video),
        )
        result = parse_url_summary(raw_result)
    except Exception as exc:
        return await _mark_failed(session, analysis_run, exc)

    result_json = result.model_dump(mode="json")
    score = _confidence(result.overall_confidence)
    now = datetime.now(timezone.utc)
    analysis_run.summary_json = result_json
    analysis_run.summary_text = result.summary
    analysis_run.confidence_score = score
    analysis_run.state = VideoAnalysisRunState.DONE
    analysis_run.finished_at = now
    video.gemini_url_summary = result.summary
    video.gemini_url_summary_json = result_json
    video.gemini_url_summary_model = resolved_model
    video.gemini_url_summary_at = now
    await session.commit()
    return {
        "analysis_run_id": analysis_run.id,
        "run_type": analysis_run.run_type,
        "state": VideoAnalysisRunState.DONE.value,
        "places": len(result.places),
        "confidence_score": score,
    }


async def transcript_candidates_for_video(
    session: AsyncSession,
    video_id: str,
) -> list[ExtractedPlaceCandidate]:
    """영상의 transcript 기반 장소 후보를 id 순서로 조회한다."""
    result = await session.execute(
        select(ExtractedPlaceCandidate)
        .where(ExtractedPlaceCandidate.video_id == video_id)
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
    result: ReconcileResult,
    analysis_run_id: int,
) -> int:
    by_id = {candidate.id: candidate for candidate in candidates}
    updated = 0
    for place in result.places:
        if not _review_decision(place):
            continue
        note = _compact(place.needs_review_reason) or "Gemini URL 분석과 자막 기반 후보가 완전히 일치하지 않는다."
        for candidate_id in place.transcript_candidate_ids:
            candidate = by_id.get(candidate_id)
            if candidate is None or candidate.match_status == MatchStatus.USER_CORRECTED:
                continue
            candidate.match_status = MatchStatus.NEEDS_REVIEW
            candidate.review_note = note
            candidate.analysis_run_id = analysis_run_id
            candidate.feature_export_status = FeatureExportStatus.PENDING.value
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
            updated += 1
    return updated


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
    try:
        await _mark_running(
            session,
            analysis_run,
            model=resolved_model,
            prompt_version=RECONCILE_PROMPT_VERSION,
        )
        if not video.gemini_url_summary_json:
            raise VideoAnalysisError("reconcile 실행 전 url_summary 결과가 필요하다")
        candidates = await transcript_candidates_for_video(session, video.video_id)
        prompt = build_reconcile_prompt(
            video=video,
            transcript_candidates=[_candidate_context(item) for item in candidates],
            url_summary=video.gemini_url_summary_json,
        )
        resolved_llm = llm or make_text_llm(runtime)
        raw_result = await asyncio.to_thread(resolved_llm, prompt)
        result = parse_reconcile(raw_result)
    except Exception as exc:
        return await _mark_failed(session, analysis_run, exc)

    result_json = result.model_dump(mode="json")
    score = _confidence(result.overall_confidence)
    now = datetime.now(timezone.utc)
    updated_candidates = _apply_reconcile_review_notes(
        candidates=candidates,
        result=result,
        analysis_run_id=analysis_run.id,
    )
    analysis_run.summary_json = result_json
    analysis_run.summary_text = result.summary
    analysis_run.confidence_score = score
    analysis_run.state = VideoAnalysisRunState.DONE
    analysis_run.finished_at = now
    video.reconciled_summary = result.summary
    video.reconciled_summary_json = result_json
    video.reconciled_summary_at = now
    await session.commit()
    return {
        "analysis_run_id": analysis_run.id,
        "run_type": analysis_run.run_type,
        "state": VideoAnalysisRunState.DONE.value,
        "places": len(result.places),
        "conflicts": len(result.conflicts),
        "updated_review_candidates": updated_candidates,
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

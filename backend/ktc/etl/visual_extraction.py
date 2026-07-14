"""프레임 비전/OCR 실험 경로 (T-173, 로드맵 PR-19).

자막·whisper가 최종 실패한 영상에서 균등 간격 프레임을 추출해 Gemini 멀티모달 **1콜**로
화면 텍스트(간판·하드섭 자막·오버레이·지도 라벨)를 OCR하고 장소명 후보를 뽑아 검수
전용 `visual` 후보를 만든다(description recall, T-168과 대칭 — 자동확정 금지는
`ktc.etl.geocode_service._RECALL_SOURCE_KINDS`가 강제한다).

**게이트 off, 완전 비활성(기본)**: `VISUAL_EXTRACTION_ENABLED`(기본 false)가 꺼져 있으면
`run_visual_extraction`은 스트림 취득·비전 호출·프레임 저장 어느 것도 하지 않고 즉시
반환한다(`frame_extraction.store_raw_media`의 kill switch 패턴과 동일). 켜져 있어도
DeepSeek 엔진에서는 `llm_client.generate_multimodal`이 `ValueError`를 던지므로(Gemini
전용, `video_analysis_service.make_youtube_url_llm`과 동일한 제약) 이 모듈도 진입 즉시
엔진을 확인해 Gemini가 아니면 no-op한다(부록 B 안전 가드).

프레임 추출은 기존 `frame_extraction` 인프라(스트림 URL 1회 확보 + FFmpeg input seeking,
다운로드 없음)를 재사용하고, 후보 persist는 `batch_poi_service._persist_candidates`를
description 경로와 공유한다(T-173 refactor). 비전 호출은 영상당 **정확히 1회**만
호출하도록 구조적으로 강제한다(반복/재분할 금지, 비용 상한).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import get_settings
from ktc.etl import frame_extraction, llm_client, media_store
from ktc.etl.batch_poi import BatchExtractedPOI
from ktc.etl.batch_poi_service import _persist_candidates
from ktc.etl.place_name import normalize_place_name
from ktc.models import (
    AssetType,
    EvidenceSourceKind,
    ExtractedPlaceCandidate,
    MediaAsset,
    YoutubeVideo,
)

logger = logging.getLogger(__name__)

# 비전 응답 alias는 배치 계약(`batch_poi.extract_batch`)과 동일한 규약을 재사용한다 —
# `_persist_candidates`가 `poi.video_id == batch의 key`로 매칭하므로, 영상당 1콜이라
# 항상 단일 alias만 쓴다.
_ALIAS = "video_001"

# Gemini 비전 응답 JSON schema. 프레임별 OCR 텍스트와 그 프레임에서 보이는 장소명
# 후보만 강제한다 — 카테고리·좌표 추론은 하지 않는다(그건 지오코딩 단계 소관).
VISUAL_OCR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "frames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frame_index": {"type": "integer"},
                    "extracted_text": {"type": "string"},
                    "place_name_candidates": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["frame_index"],
            },
        },
    },
    "required": ["frames"],
}


class VisualFrameOcrResult(BaseModel):
    """프레임 1장의 비전 OCR 결과."""

    frame_index: int
    extracted_text: str = ""
    place_name_candidates: list[str] = Field(default_factory=list)


class VisualOcrResult(BaseModel):
    """영상 1건 비전 1콜의 전체 응답."""

    frames: list[VisualFrameOcrResult] = Field(default_factory=list)


class VisualExtractionError(RuntimeError):
    """프레임 비전/OCR 추출 실패(스트림 확보·비전 호출·응답 파싱 실패 포함)."""


class VisionCaller(Protocol):
    async def __call__(self, parts: list[dict[str, Any]]) -> str:
        """멀티모달 parts를 받아 비전 응답 JSON 문자열을 반환한다."""


@dataclass(frozen=True)
class ExtractedFrame:
    """추출·저장된 프레임 1장(evidence에는 asset_id/timestamp만 남고 bytes는 버려진다)."""

    frame_index: int
    timestamp_seconds: float
    asset_id: int
    object_key: str
    jpeg_bytes: bytes


def compute_frame_timestamps(
    duration_seconds: float | int | None,
    *,
    count: int,
    trim_fraction: float = 0.05,
) -> list[float]:
    """영상 길이 기준 균등 간격 timestamp 목록을 만든다(앞뒤 `trim_fraction` 트림).

    intro/outro(오프닝 로고·엔딩 카드)는 화면 텍스트 신호가 약해 앞뒤 5%를 제외한
    구간에서 균등 분할한다. duration이 없거나 0 이하, count<=0이면 빈 목록을 반환한다
    (호출부가 스킵 판단에 쓴다).
    """
    if not duration_seconds or duration_seconds <= 0 or count <= 0:
        return []
    duration = float(duration_seconds)
    trim = duration * max(0.0, min(trim_fraction, 0.49))
    start, end = trim, duration - trim
    if end <= start:
        start, end = 0.0, duration
    if count == 1:
        return [(start + end) / 2]
    step = (end - start) / (count - 1)
    return [start + step * i for i in range(count)]


async def select_visual_targets(
    session: AsyncSession, *, limit: int = 1
) -> list[YoutubeVideo]:
    """visual 추출 대상 영상을 고른다(자막·whisper 최종 실패 + 기존 시도 없음).

    대상: `transcript_source IS NULL AND transcript_failure_code IS NOT NULL`
    (자막+whisper 전 provider 최종 실패, `youtube_video.py`)이고 아직 visual 후보
    또는 프레임 asset이 없는 영상. 새 컬럼(`visual_extraction_status` 등) 없이 기존
    `extracted_place_candidates`/`media_assets`로 재선별 idempotency를 보장한다
    (T-173 계획서 §마이그레이션 필요 여부 — 불필요 결정).
    """
    settings = get_settings()
    existing_visual = select(ExtractedPlaceCandidate.video_id).where(
        ExtractedPlaceCandidate.source_kind == EvidenceSourceKind.VISUAL.value,
        ExtractedPlaceCandidate.deleted_at.is_(None),
    )
    existing_frames = select(MediaAsset.video_id).where(
        MediaAsset.asset_type == AssetType.FRAME.value,
        MediaAsset.video_id.is_not(None),
    )
    stmt = (
        select(YoutubeVideo)
        .where(
            YoutubeVideo.transcript_source.is_(None),
            YoutubeVideo.transcript_failure_code.is_not(None),
            YoutubeVideo.duration_seconds.is_not(None),
            YoutubeVideo.duration_seconds >= settings.VISUAL_MIN_DURATION_SECONDS,
            YoutubeVideo.video_id.not_in(existing_visual),
            YoutubeVideo.video_id.not_in(existing_frames),
        )
        .order_by(YoutubeVideo.video_id)
        .limit(max(1, limit))
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def build_visual_ocr_prompt(frame_count: int) -> str:
    """비전 1콜 프롬프트 — 프레임별 화면 텍스트 OCR + 장소명 후보만 요청한다."""
    return (
        f"아래 {frame_count}장은 같은 한국 여행 유튜브 영상에서 균등한 간격으로 뽑은 "
        "프레임이다(순서대로 frame_index=0..N-1). 각 프레임의 화면에 보이는 텍스트를 "
        "그대로 옮겨 적어라(간판·상호명·메뉴판·자막(하드섭)·오버레이 텍스트·지도 "
        "라벨 포함). 그 프레임에서 실제 방문 장소로 보이는 구체적 상호명·지명이 "
        "있으면 place_name_candidates에 적어라(브랜드·체인 단독 이름은 지점명이 "
        "분명할 때만, 확실하지 않으면 비워 둬라). 반드시 주어진 JSON Schema에 맞는 "
        "JSON만 출력하라."
    )


def _default_vision_caller(runtime: llm_client.LlmRuntime) -> VisionCaller:
    async def call(parts: list[dict[str, Any]]) -> str:
        return await llm_client.generate_multimodal(
            runtime,
            parts,
            response_schema=VISUAL_OCR_RESPONSE_SCHEMA,
            timeout_seconds=120.0,
        )

    return call


def parse_visual_ocr(payload: str) -> VisualOcrResult:
    """비전 응답 JSON을 파싱·검증한다."""
    try:
        data = json.loads(payload)
        return VisualOcrResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise VisualExtractionError(f"비전 OCR 응답 파싱 실패: {exc}") from exc


def build_visual_pois(
    *,
    alias: str,
    frame_results: list[VisualFrameOcrResult],
    frame_timestamps: dict[int, float],
) -> list[BatchExtractedPOI]:
    """프레임별 OCR 결과를 (영상, 정규화 장소명) 기준으로 dedup해 POI 목록으로 만든다.

    같은 이름이 여러 프레임에 등장하면 처음 등장한 프레임의 timestamp·OCR 텍스트를
    쓴다(evidence 근거는 candidate 전체 `frames` 목록에 별도로 보존되므로 손실 없음).
    `_persist_candidates`가 그대로 소비할 수 있도록 `batch_poi.BatchExtractedPOI`를
    재사용한다(POI dataclass 이중 정의 회피).
    """
    seen: dict[str, BatchExtractedPOI] = {}
    for frame in frame_results:
        for raw_name in frame.place_name_candidates:
            name = (raw_name or "").strip()
            if not name:
                continue
            key = normalize_place_name(name)
            if not key or key in seen:
                continue
            timestamp = frame_timestamps.get(frame.frame_index)
            seen[key] = BatchExtractedPOI(
                video_id=alias,
                official_name=name,
                location_hint=None,
                category_code=None,
                timestamp_start=(
                    frame_extraction.format_ffmpeg_timestamp(timestamp)
                    if timestamp is not None
                    else None
                ),
                timestamp_end=None,
                speaker_note=(frame.extracted_text or None),
                # 이 서비스는 국내 여행지만 다루고 화면 텍스트만으로 해외 여부를 판정할
                # 근거가 약하므로, batch_poi 시스템 지시문의 "확실하지 않으면 true"
                # 규약을 그대로 따른다(자동확정은 어차피 recall source_kind 예외가 막는다).
                is_domestic=True,
                evidence_quote=(frame.extracted_text or None),
                confidence=None,
            )
    return list(seen.values())


async def _extract_video_frames(
    session: AsyncSession,
    store: media_store.MediaStore,
    *,
    video: YoutubeVideo,
    video_url: str,
    frame_count: int,
    stream_url_resolver: frame_extraction.StreamUrlResolver,
    frame_extractor: frame_extraction.FrameExtractor,
) -> list[ExtractedFrame]:
    """스트림 URL을 1회 확보하고 균등 간격 프레임을 다운로드 없이 추출·저장한다."""
    stream_url = await asyncio.to_thread(stream_url_resolver, video_url)
    if not stream_url:
        raise VisualExtractionError("yt-dlp 스트림 URL 확보 실패")

    timestamps = compute_frame_timestamps(video.duration_seconds, count=frame_count)
    frames: list[ExtractedFrame] = []
    for index, timestamp in enumerate(timestamps):
        jpeg = await asyncio.to_thread(frame_extractor, stream_url, timestamp)
        object_key = frame_extraction.build_frame_object_key(video.video_id, timestamp)
        asset = await media_store.store_and_record(
            session,
            store,
            asset_type=AssetType.FRAME,
            object_key=object_key,
            data=jpeg,
            content_type="image/jpeg",
            video_id=video.video_id,
            place_id=None,
        )
        frames.append(
            ExtractedFrame(
                frame_index=index,
                timestamp_seconds=timestamp,
                asset_id=asset.id,
                object_key=object_key,
                jpeg_bytes=jpeg,
            )
        )
    return frames


def _build_vision_parts(frames: list[ExtractedFrame], prompt: str) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = [
        {
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(frame.jpeg_bytes).decode("ascii"),
            }
        }
        for frame in frames
    ]
    parts.append({"text": prompt})
    return parts


async def run_visual_extraction_for_video(
    session: AsyncSession,
    store: media_store.MediaStore,
    *,
    video: YoutubeVideo,
    runtime: llm_client.LlmRuntime,
    stream_url_resolver: frame_extraction.StreamUrlResolver = frame_extraction.resolve_stream_url_ytdlp,
    frame_extractor: frame_extraction.FrameExtractor = frame_extraction.extract_jpeg_with_ffmpeg,
    vision_caller: VisionCaller | None = None,
) -> dict[str, Any]:
    """영상 1건의 프레임 추출 + 비전 1콜 + 후보 persist + 지오코딩을 실행한다.

    호출자(`run_visual_extraction`)가 이미 플래그·엔진 가드를 통과시킨 뒤에만 부른다 —
    이 함수 자체는 가드를 재확인하지 않는다(단일 영상 단위 재사용을 위해 얇게 유지).
    """
    settings = get_settings()
    video_url = video.canonical_url or video.url
    if not video_url:
        return {"skipped": "no_video_url", "video_id": video.video_id, "created_candidates": 0}

    frame_count = max(1, min(settings.VISUAL_FRAME_COUNT_DEFAULT, settings.VISUAL_FRAME_MAX))
    frames = await _extract_video_frames(
        session,
        store,
        video=video,
        video_url=video_url,
        frame_count=frame_count,
        stream_url_resolver=stream_url_resolver,
        frame_extractor=frame_extractor,
    )
    await session.commit()
    if not frames:
        return {"skipped": "no_frames", "video_id": video.video_id, "created_candidates": 0}

    prompt = build_visual_ocr_prompt(len(frames))
    parts = _build_vision_parts(frames, prompt)
    caller = vision_caller or _default_vision_caller(runtime)
    # 영상당 정확히 1회만 호출한다(비용 상한, 반복/재분할 금지 — T-173 §5-2).
    try:
        raw = await caller(parts)
    except llm_client.LlmRequestError as exc:
        raise VisualExtractionError(f"Gemini 비전 OCR 호출 실패: {exc}") from exc
    ocr_result = parse_visual_ocr(raw)

    frame_timestamps = {frame.frame_index: frame.timestamp_seconds for frame in frames}
    pois = build_visual_pois(
        alias=_ALIAS, frame_results=ocr_result.frames, frame_timestamps=frame_timestamps
    )
    if not pois:
        return {
            "video_id": video.video_id,
            "created_candidates": 0,
            "frames": len(frames),
        }

    frame_evidence = [
        {
            "asset_id": frame.asset_id,
            "timestamp_seconds": frame.timestamp_seconds,
            "frame_index": frame.frame_index,
        }
        for frame in frames
    ]
    batch: dict[str, dict[str, Any]] = {
        _ALIAS: {
            "video": video,
            "transcript_source": "visual",
            "asset_id": None,
            "corrected": None,
            "raw_text": None,
            "source_kind": EvidenceSourceKind.VISUAL.value,
            "frames": frame_evidence,
        }
    }
    created = await _persist_candidates(
        session,
        batch=batch,
        pois=pois,
        normalized_default_category=None,
    )
    await session.commit()

    # 지오코딩은 수행하되(좌표·주소를 검수 evidence로 남김) 자동확정은
    # `geocode_service._RECALL_SOURCE_KINDS`(VISUAL 포함)가 구조적으로 막는다.
    if created:
        from ktc.etl import postprocess_service

        await postprocess_service.geocode_candidates(session, created)

    return {
        "video_id": video.video_id,
        "created_candidates": len(created),
        "frames": len(frames),
    }


async def run_visual_extraction(
    session: AsyncSession,
    store: media_store.MediaStore,
    *,
    runtime: llm_client.LlmRuntime,
    video_ids: list[str] | None = None,
    limit: int = 1,
    stream_url_resolver: frame_extraction.StreamUrlResolver = frame_extraction.resolve_stream_url_ytdlp,
    frame_extractor: frame_extraction.FrameExtractor = frame_extraction.extract_jpeg_with_ffmpeg,
    vision_caller: VisionCaller | None = None,
) -> dict[str, Any]:
    """T-173 visual extraction job의 단일 진입점(게이트·DeepSeek 엔진 가드 포함).

    **게이트 확인이 이 함수의 첫 동작이다** — `VISUAL_EXTRACTION_ENABLED`가 꺼져
    있으면(기본) 로그 1줄만 남기고 즉시 반환한다. 스트림 resolver·비전 콜러블·
    `store_and_record` 어느 것도 호출하지 않는다(대상 선별 쿼리조차 실행하지 않는다).

    켜져 있어도 런타임 엔진이 DeepSeek이면(`generate_multimodal`은 Gemini 전용이라
    ValueError를 던진다, `llm_client.py` 문서·`video_analysis_service.make_youtube_url_llm`
    참고) 마찬가지로 no-op한다(부록 B 안전 가드) — 배치 job이 예외로 죽지 않는다.
    """
    settings = get_settings()
    if not settings.VISUAL_EXTRACTION_ENABLED:
        logger.info("visual_extraction: VISUAL_EXTRACTION_ENABLED=false — no-op")
        return {"skipped": "flag_disabled", "processed_videos": 0, "created_candidates": 0}
    if runtime.is_deepseek:
        logger.info(
            "visual_extraction: DeepSeek 엔진(model=%s)은 멀티모달 비전을 지원하지 않아 "
            "no-op — generate_multimodal은 Gemini 전용이다.",
            runtime.model,
        )
        return {
            "skipped": "engine_not_gemini",
            "processed_videos": 0,
            "created_candidates": 0,
        }

    if video_ids:
        result = await session.execute(
            select(YoutubeVideo).where(YoutubeVideo.video_id.in_(video_ids))
        )
        targets = list(result.scalars().all())
    else:
        targets = await select_visual_targets(session, limit=limit)

    results: list[dict[str, Any]] = []
    for video in targets:
        outcome = await run_visual_extraction_for_video(
            session,
            store,
            video=video,
            runtime=runtime,
            stream_url_resolver=stream_url_resolver,
            frame_extractor=frame_extractor,
            vision_caller=vision_caller,
        )
        results.append(outcome)

    return {
        "processed_videos": len(results),
        "created_candidates": sum(int(r.get("created_candidates") or 0) for r in results),
        "results": results,
    }

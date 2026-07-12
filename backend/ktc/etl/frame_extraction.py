"""대표 프레임 추출 서비스 (T-009).

Gemini가 식별한 POI 시작 시각에 5~10초 오프셋을 더한 뒤, `yt-dlp`로 직접
스트림 URL을 확보하고 FFmpeg Input Seeking(`-ss`를 `-i` 앞에 배치)으로 JPEG 한
장을 추출한다. 추출한 JPEG는 RustFS 미디어 버킷에 저장하고
`media_assets`에 기록한다.

외부 도구(`yt-dlp`, FFmpeg)는 지연 import·주입형 함수로 감싸 테스트가 로컬
바이너리 설치 여부에 의존하지 않게 한다.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ktc.core.config import get_settings
from ktc.etl import media_store
from ktc.models import AssetType, MediaAsset, VideoPlaceMapping

logger = logging.getLogger(__name__)


class FrameExtractionError(RuntimeError):
    """대표 프레임 추출 실패."""


class StreamUrlResolver(Protocol):
    def __call__(self, video_url: str) -> str | None:
        """영상 URL에서 FFmpeg이 읽을 수 있는 직접 스트림 URL을 반환한다."""


class FrameExtractor(Protocol):
    def __call__(self, stream_url: str, timestamp_seconds: float) -> bytes:
        """스트림 URL과 시각을 받아 JPEG bytes를 반환한다."""


@dataclass(frozen=True)
class FrameExtractionResult:
    video_id: str
    timestamp_seconds: float
    object_key: str
    asset: MediaAsset
    mapping_id: int | None = None


def parse_timestamp(value: str | int | float) -> float:
    """`HH:MM:SS`, `MM:SS`, `SS` 또는 숫자 초 값을 float 초로 변환한다."""
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        raw = value.strip()
        if not raw:
            raise ValueError("timestamp가 비어 있다")
        parts = raw.split(":")
        if len(parts) > 3:
            raise ValueError(f"지원하지 않는 timestamp 형식: {value}")
        try:
            numbers = [float(p) for p in parts]
        except ValueError as exc:
            raise ValueError(f"지원하지 않는 timestamp 형식: {value}") from exc

        seconds = 0.0
        for number in numbers:
            seconds = seconds * 60 + number

    if seconds < 0:
        raise ValueError("timestamp는 음수일 수 없다")
    return seconds


def frame_timestamp_seconds(
    timestamp_start: str | int | float, *, offset_seconds: float = 5.0
) -> float:
    """POI 시작 시각에 대표 프레임 오프셋을 더한다."""
    if offset_seconds < 0:
        raise ValueError("offset_seconds는 음수일 수 없다")
    return parse_timestamp(timestamp_start) + offset_seconds


def format_ffmpeg_timestamp(seconds: float) -> str:
    """FFmpeg `-ss` 인자용 `HH:MM:SS.mmm` 문자열."""
    total_ms = int(round(seconds * 1000))
    hh, rem = divmod(total_ms, 3_600_000)
    mm, rem = divmod(rem, 60_000)
    ss, ms = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{ms:03d}"


def _safe_object_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe or "unknown"


def build_frame_object_key(video_id: str, timestamp_seconds: float) -> str:
    """RustFS 대표 프레임 객체 키."""
    stamp = format_ffmpeg_timestamp(timestamp_seconds).replace(":", "_").replace(".", "_")
    return f"{_safe_object_part(video_id)}/frames/frame_{stamp}.jpg"


def build_raw_media_object_key(video_id: str, filename: str) -> str:
    """RustFS 원본 동영상/오디오 객체 키."""
    return f"{_safe_object_part(video_id)}/raw/{_safe_object_part(filename)}"


def _numeric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def select_stream_url(info: dict[str, Any]) -> str | None:
    """`yt-dlp` `extract_info` 결과에서 프레임 추출용 스트림 URL을 고른다."""
    direct = info.get("url")
    if isinstance(direct, str) and direct:
        return direct

    formats = info.get("formats")
    if not isinstance(formats, list):
        return None

    candidates = [
        fmt
        for fmt in formats
        if isinstance(fmt, dict)
        and isinstance(fmt.get("url"), str)
        and fmt.get("vcodec") not in (None, "none")
    ]
    if not candidates:
        return None

    best = max(candidates, key=lambda fmt: (_numeric(fmt.get("height")), _numeric(fmt.get("tbr"))))
    return best["url"]


def resolve_stream_url_ytdlp(video_url: str) -> str | None:
    """`yt-dlp`로 다운로드 없이 직접 스트림 URL을 확보한다."""
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        return None

    options = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "format": "bestvideo[ext=mp4]/bestvideo/best",
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    return select_stream_url(info)


def extract_jpeg_with_ffmpeg(
    stream_url: str,
    timestamp_seconds: float,
    *,
    timeout: float = 60.0,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> bytes:
    """FFmpeg Input Seeking으로 JPEG 한 장을 stdout에서 읽는다."""
    ffmpeg_path = get_settings().FFMPEG_PATH or "ffmpeg"
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        format_ffmpeg_timestamp(timestamp_seconds),
        "-i",
        stream_url,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-f",
        "image2",
        "pipe:1",
    ]
    try:
        completed = runner(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise FrameExtractionError(
            f"FFmpeg 실행 파일을 찾을 수 없습니다: {ffmpeg_path}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FrameExtractionError("FFmpeg 대표 프레임 추출 타임아웃") from exc
    if completed.returncode != 0:
        stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
        raise FrameExtractionError(f"FFmpeg 대표 프레임 추출 실패: {stderr}")
    if not completed.stdout:
        raise FrameExtractionError("FFmpeg 대표 프레임 출력이 비어 있다")
    return completed.stdout


async def store_raw_media(
    session: AsyncSession,
    store: media_store.MediaStore,
    *,
    video_id: str,
    filename: str,
    data: bytes | None = None,
    fileobj: BinaryIO | None = None,
    content_type: str | None = None,
) -> MediaAsset | None:
    """원본 동영상 또는 오디오를 RustFS에 무기한 보존한다.

    Phase -1 provider 정책 kill switch(`RAW_MEDIA_STORE_ENABLED`, T-158)가
    꺼져 있으면 저장을 스킵하고 None을 반환한다(작업 로그 1줄 기록).
    다운로드 자체는 이 플래그가 막지 않는다(저장 게이트).
    """
    if not get_settings().RAW_MEDIA_STORE_ENABLED:
        logger.info(
            "RAW_MEDIA_STORE_ENABLED=false — 원본 미디어 저장 스킵 "
            "(video_id=%s, filename=%s, Phase -1 정책 게이트 docs/provider-policy.md)",
            video_id,
            filename,
        )
        return None
    if (data is None) == (fileobj is None):
        raise ValueError("data 또는 fileobj 중 하나만 전달해야 한다")
    object_key = build_raw_media_object_key(video_id, filename)
    if fileobj is not None:
        return await media_store.store_stream_and_record(
            session,
            store,
            asset_type=AssetType.RAW_VIDEO,
            object_key=object_key,
            fileobj=fileobj,
            content_type=content_type,
            video_id=video_id,
        )
    return await media_store.store_and_record(
        session,
        store,
        asset_type=AssetType.RAW_VIDEO,
        object_key=object_key,
        data=data,
        content_type=content_type,
        video_id=video_id,
    )


async def extract_and_store_frame(
    session: AsyncSession,
    store: media_store.MediaStore,
    *,
    video_id: str,
    video_url: str,
    timestamp_start: str | int | float,
    offset_seconds: float = 5.0,
    place_id: int | None = None,
    mapping_id: int | None = None,
    stream_url_resolver: StreamUrlResolver = resolve_stream_url_ytdlp,
    frame_extractor: FrameExtractor = extract_jpeg_with_ffmpeg,
) -> FrameExtractionResult:
    """대표 프레임을 추출해 RustFS에 저장하고 선택적으로 mapping에 연결한다."""
    mapping: VideoPlaceMapping | None = None
    if mapping_id is not None:
        mapping = await session.get(VideoPlaceMapping, mapping_id)
        if mapping is None:
            raise FrameExtractionError(f"존재하지 않는 video_place_mapping: {mapping_id}")
        if place_id is None:
            place_id = mapping.place_id

    seconds = frame_timestamp_seconds(timestamp_start, offset_seconds=offset_seconds)
    stream_url = await asyncio.to_thread(stream_url_resolver, video_url)
    if not stream_url:
        raise FrameExtractionError("yt-dlp 스트림 URL 확보 실패")

    jpeg = await asyncio.to_thread(frame_extractor, stream_url, seconds)
    object_key = build_frame_object_key(video_id, seconds)
    asset = await media_store.store_and_record(
        session,
        store,
        asset_type=AssetType.FRAME,
        object_key=object_key,
        data=jpeg,
        content_type="image/jpeg",
        video_id=video_id,
        place_id=place_id,
    )

    if mapping is not None:
        mapping.frame_asset_id = asset.id
        await session.commit()
        await session.refresh(mapping)

    return FrameExtractionResult(
        video_id=video_id,
        timestamp_seconds=seconds,
        object_key=object_key,
        asset=asset,
        mapping_id=mapping_id,
    )

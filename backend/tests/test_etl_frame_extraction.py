"""대표 프레임 추출 서비스 테스트."""

from __future__ import annotations

import io
import subprocess

import pytest

from app.etl import frame_extraction
from app.etl.frame_extraction import (
    FrameExtractionError,
    build_frame_object_key,
    extract_and_store_frame,
    extract_jpeg_with_ffmpeg,
    frame_timestamp_seconds,
    parse_timestamp,
    select_stream_url,
    store_raw_media,
)
from app.etl.media_store import InMemoryMediaStore
from app.models import (
    AssetType,
    MediaAsset,
    TravelPlace,
    VideoPlaceMapping,
    YoutubeVideo,
)


def test_parse_timestamp_variants_and_offset():
    assert parse_timestamp("00:03:25") == 205
    assert parse_timestamp("03:25") == 205
    assert parse_timestamp("25") == 25
    assert parse_timestamp(12.5) == 12.5
    assert frame_timestamp_seconds("00:03:25", offset_seconds=7) == 212


def test_parse_timestamp_rejects_invalid_values():
    with pytest.raises(ValueError):
        parse_timestamp("")
    with pytest.raises(ValueError):
        parse_timestamp("-1")
    with pytest.raises(ValueError):
        parse_timestamp("01:02:03:04")


def test_build_frame_object_key_sanitizes_video_id():
    key = build_frame_object_key("video/id 한글", 205)
    assert key == "video_id/frames/frame_00_03_25_000.jpg"


def test_select_stream_url_prefers_highest_video_format():
    info = {
        "formats": [
            {"url": "audio", "vcodec": "none", "height": None, "tbr": 128},
            {"url": "low", "vcodec": "avc1", "height": 360, "tbr": 700},
            {"url": "high", "vcodec": "avc1", "height": 1080, "tbr": 2000},
        ]
    }
    assert select_stream_url(info) == "high"


def test_select_stream_url_direct_url_wins():
    assert select_stream_url({"url": "direct", "formats": [{"url": "other"}]}) == "direct"


def test_select_stream_url_rejects_audio_only_formats():
    info = {
        "formats": [
            {"url": "audio", "vcodec": "none", "height": None, "tbr": 128},
        ]
    }
    assert select_stream_url(info) is None


def test_extract_jpeg_with_ffmpeg_uses_input_seeking(monkeypatch):
    captured = {}

    class SettingsStub:
        FFMPEG_PATH = "ffmpeg"

    monkeypatch.setattr(frame_extraction, "get_settings", lambda: SettingsStub())

    def runner(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout=b"\xff\xd8jpeg", stderr=b"")

    data = extract_jpeg_with_ffmpeg("https://stream", 205.25, runner=runner)
    assert data.startswith(b"\xff\xd8")

    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg"
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "00:03:25.250"
    assert cmd[cmd.index("-i") + 1] == "https://stream"
    assert cmd[-1] == "pipe:1"
    assert captured["kwargs"]["stdout"] == subprocess.PIPE
    assert captured["kwargs"]["stderr"] == subprocess.PIPE


def test_extract_jpeg_with_ffmpeg_uses_configured_binary(monkeypatch):
    captured = {}

    class SettingsStub:
        FFMPEG_PATH = r"F:\dev\tripmate-agent\.local\ffmpeg\bin\ffmpeg.exe"

    monkeypatch.setattr(frame_extraction, "get_settings", lambda: SettingsStub())

    def runner(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=b"\xff\xd8jpeg", stderr=b"")

    data = extract_jpeg_with_ffmpeg("https://stream", 10, runner=runner)

    assert data.startswith(b"\xff\xd8")
    assert captured["cmd"][0] == SettingsStub.FFMPEG_PATH


def test_extract_jpeg_with_ffmpeg_raises_on_failure():
    def runner(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"boom")

    with pytest.raises(FrameExtractionError, match="boom"):
        extract_jpeg_with_ffmpeg("https://stream", 0, runner=runner)


def test_extract_jpeg_with_ffmpeg_wraps_timeout():
    def runner(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=kwargs["timeout"])

    with pytest.raises(FrameExtractionError, match="타임아웃"):
        extract_jpeg_with_ffmpeg("https://stream", 0, runner=runner)


def test_extract_jpeg_with_ffmpeg_wraps_missing_binary(monkeypatch):
    class SettingsStub:
        FFMPEG_PATH = r"F:\missing\ffmpeg.exe"

    monkeypatch.setattr(frame_extraction, "get_settings", lambda: SettingsStub())

    def runner(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    with pytest.raises(FrameExtractionError, match="실행 파일을 찾을 수 없습니다"):
        extract_jpeg_with_ffmpeg("https://stream", 0, runner=runner)


async def _make_video_place_mapping(session):
    video = YoutubeVideo(video_id="v1", title="제주", url="https://youtu.be/v1", channel_id="c")
    place = TravelPlace(name="월정리", latitude=33.55, longitude=126.78, is_geocoded=True)
    session.add_all([video, place])
    await session.commit()
    await session.refresh(place)
    mapping = VideoPlaceMapping(
        video_id=video.video_id,
        place_id=place.place_id,
        ai_summary="월정리 소개",
        timestamp_start="00:01:00",
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return video, place, mapping


async def test_extract_and_store_frame_records_asset_and_mapping(session):
    video, place, mapping = await _make_video_place_mapping(session)
    store = InMemoryMediaStore()

    result = await extract_and_store_frame(
        session,
        store,
        video_id=video.video_id,
        video_url=video.url,
        timestamp_start=mapping.timestamp_start,
        offset_seconds=5,
        mapping_id=mapping.id,
        stream_url_resolver=lambda url: "https://stream/v1",
        frame_extractor=lambda stream_url, seconds: b"\xff\xd8frame",
    )

    assert result.timestamp_seconds == 65
    assert result.object_key == "v1/frames/frame_00_01_05_000.jpg"
    assert result.asset.asset_type == AssetType.FRAME
    assert result.asset.bucket == "krtour-map"
    assert result.asset.object_key == "features/v1/frames/frame_00_01_05_000.jpg"
    assert result.asset.video_id == video.video_id
    assert result.asset.place_id == place.place_id
    assert ("krtour-map", result.asset.object_key) in store.objects

    refreshed_mapping = await session.get(VideoPlaceMapping, mapping.id)
    assert refreshed_mapping.frame_asset_id == result.asset.id


async def test_extract_and_store_frame_fails_before_upload_when_mapping_missing(session):
    store = InMemoryMediaStore()
    with pytest.raises(FrameExtractionError, match="존재하지 않는"):
        await extract_and_store_frame(
            session,
            store,
            video_id="v1",
            video_url="https://youtu.be/v1",
            timestamp_start="00:00:00",
            mapping_id=999,
            stream_url_resolver=lambda url: "https://stream/v1",
            frame_extractor=lambda stream_url, seconds: b"\xff\xd8frame",
        )
    assert store.objects == {}


async def test_store_raw_media_records_raw_video_asset(session):
    video = YoutubeVideo(video_id="vraw", title="원본", url="https://youtu.be/vraw", channel_id="c")
    session.add(video)
    await session.commit()

    store = InMemoryMediaStore()
    asset = await store_raw_media(
        session,
        store,
        video_id=video.video_id,
        filename="source.mp4",
        data=b"video-bytes",
        content_type="video/mp4",
    )

    assert asset.asset_type == AssetType.RAW_VIDEO
    assert asset.bucket == "krtour-map"
    assert asset.object_key == "features/vraw/raw/source.mp4"
    assert ("krtour-map", asset.object_key) in store.objects
    assert isinstance(asset, MediaAsset)


async def test_store_raw_media_stream_records_raw_video_asset(session):
    video = YoutubeVideo(
        video_id="vstream",
        title="원본",
        url="https://youtu.be/v",
        channel_id="c",
    )
    session.add(video)
    await session.commit()

    store = InMemoryMediaStore()
    asset = await store_raw_media(
        session,
        store,
        video_id=video.video_id,
        filename="source.mp4",
        fileobj=io.BytesIO(b"streamed-video-bytes"),
        content_type="video/mp4",
    )

    assert asset.asset_type == AssetType.RAW_VIDEO
    assert asset.object_key == "features/vstream/raw/source.mp4"
    assert asset.size_bytes == len(b"streamed-video-bytes")
    assert asset.sha256 == frame_extraction.media_store.sha256_hex(b"streamed-video-bytes")
    assert store.objects[("krtour-map", asset.object_key)] == b"streamed-video-bytes"

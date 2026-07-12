"""Phase -1 provider 정책 kill switch 테스트 (T-158, DB 불필요).

`RAW_MEDIA_DOWNLOAD_ENABLED`/`GOOGLE_PLACE_SEARCH_ENABLED`가 꺼졌을 때 해당
경로가 외부 부작용(저장·HTTP 호출) 없이 스킵되는지 검증한다. 게이트는 세션/HTTP
사용 전에 반환하므로 PostgreSQL 없이 실행된다.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from ktc.core.config import Settings
from ktc.etl import frame_extraction, place_search


class _GatesOffSettings:
    """kill switch가 모두 꺼진 설정 스텁."""

    RAW_MEDIA_DOWNLOAD_ENABLED = False
    GOOGLE_PLACE_SEARCH_ENABLED = False


@pytest.mark.asyncio
async def test_store_raw_media_skips_when_download_disabled(monkeypatch, caplog):
    """게이트 off면 저장 없이 None을 반환하고 로그 1줄을 남긴다."""
    monkeypatch.setattr(frame_extraction, "get_settings", lambda: _GatesOffSettings())
    with caplog.at_level(logging.INFO, logger="ktc.etl.frame_extraction"):
        result = await frame_extraction.store_raw_media(
            None,  # 게이트가 세션/스토어 사용 전에 반환한다(DB 불필요).
            None,
            video_id="vid123",
            filename="video.mp4",
            data=b"fake-bytes",
        )
    assert result is None
    assert any(
        "RAW_MEDIA_DOWNLOAD_ENABLED=false" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_store_raw_media_disabled_skips_before_arg_validation(monkeypatch):
    """게이트 off면 data/fileobj 검증(ValueError)보다 스킵이 먼저다."""
    monkeypatch.setattr(frame_extraction, "get_settings", lambda: _GatesOffSettings())
    # data와 fileobj 둘 다 없으면 평소에는 ValueError지만, 게이트가 먼저 반환한다.
    assert (
        await frame_extraction.store_raw_media(
            None, None, video_id="vid123", filename="video.mp4"
        )
        is None
    )


@pytest.mark.asyncio
async def test_search_google_places_disabled_raises_without_http_call(monkeypatch):
    """게이트 off면 HTTP 호출 없이 disabled 사유 예외를 던진다."""
    monkeypatch.setattr(place_search, "get_settings", lambda: _GatesOffSettings())

    def handler(request):  # pragma: no cover - 호출되면 게이트 실패
        raise AssertionError("GOOGLE_PLACE_SEARCH_ENABLED=false면 HTTP 호출이 없어야 한다")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(place_search.PlaceSearchProviderDisabled) as exc_info:
            await place_search.search_google_places(
                client, query="감천문화마을", api_key="k"
            )
    # /place-search 호출부는 예외 문자열을 errors.google로 노출한다 — disabled 사유 포함.
    assert "disabled" in str(exc_info.value)
    assert "GOOGLE_PLACE_SEARCH_ENABLED" in str(exc_info.value)


def test_kill_switch_defaults_keep_current_behavior():
    """기본값은 true(현행 동작 유지) — 조용한 동작 변경 금지 (T-158)."""
    settings = Settings(_env_file=None)
    assert settings.RAW_MEDIA_DOWNLOAD_ENABLED is True
    assert settings.GOOGLE_PLACE_SEARCH_ENABLED is True

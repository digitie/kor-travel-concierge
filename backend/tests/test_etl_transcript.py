"""transcript provider 체인 테스트."""

from __future__ import annotations

from ktc.etl import transcript
from ktc.etl.transcript import TranscriptResult, TranscriptSegment, get_transcript


def _ok_provider(source):
    def provider(video_id):
        return TranscriptResult(
            video_id=video_id,
            source=source,
            segments=[TranscriptSegment(start=5.0, text="안녕하세요"),
                      TranscriptSegment(start=65.0, text="여기는 제주")],
        )
    return provider


def _none_provider(video_id):
    return None


def test_transcript_result_text_and_timestamps():
    r = TranscriptResult(
        video_id="v",
        source="transcript_api",
        segments=[TranscriptSegment(0.0, "a"), TranscriptSegment(75.0, "b")],
    )
    assert r.text == "a\nb"
    assert r.to_timestamped_text() == "[00:00] a\n[01:15] b"


def test_chain_uses_first_success():
    result = get_transcript("vid", providers=(_ok_provider("transcript_api"), _ok_provider("yt-dlp")))
    assert result is not None
    assert result.source == "transcript_api"


def test_chain_falls_back_on_none():
    result = get_transcript("vid", providers=(_none_provider, _ok_provider("yt-dlp")))
    assert result is not None
    assert result.source == "yt-dlp"


def test_chain_all_fail_returns_none():
    assert get_transcript("vid", providers=(_none_provider, _none_provider)) is None


def test_lazy_providers_return_none_without_libs():
    # 라이브러리 미설치 환경에서 graceful None
    assert transcript.fetch_via_transcript_api("vid") is None
    assert transcript.fetch_via_ytdlp("vid") is None
    assert transcript.transcribe_via_whisper("vid") is None


async def test_get_transcript_async():
    result = await transcript.get_transcript_async(
        "vid", providers=(_ok_provider("transcript_api"),)
    )
    assert result is not None
    assert result.source == "transcript_api"

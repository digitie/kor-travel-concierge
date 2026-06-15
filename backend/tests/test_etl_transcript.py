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


def test_fetch_via_transcript_api_supports_new_instance_api(monkeypatch):
    """youtube-transcript-api 1.x(.fetch) 경로를 지원한다(이슈 #76)."""
    import sys
    import types

    class _Fetched:
        def to_raw_data(self):
            return [
                {"start": 0.0, "text": "제주 카멜리아힐"},
                {"start": 12.0, "text": "수국 명소"},
            ]

    class _NewApi:  # get_transcript 없음 → 신 API 경로로 분기
        def fetch(self, video_id, languages=None):
            return _Fetched()

    fake_mod = types.ModuleType("youtube_transcript_api")
    fake_mod.YouTubeTranscriptApi = _NewApi
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake_mod)

    result = transcript.fetch_via_transcript_api("vid")
    assert result is not None
    assert result.source == "transcript_api"
    assert [s.text for s in result.segments] == ["제주 카멜리아힐", "수국 명소"]
    assert result.segments[1].start == 12.0


async def test_get_transcript_async():
    result = await transcript.get_transcript_async(
        "vid", providers=(_ok_provider("transcript_api"),)
    )
    assert result is not None
    assert result.source == "transcript_api"

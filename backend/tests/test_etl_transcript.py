"""transcript provider 체인 + 관측(T-164) 테스트."""

from __future__ import annotations

import sys
import types
from pathlib import Path

from ktc.etl import transcript
from ktc.etl.transcript import (
    TranscriptAttempt,
    TranscriptOutcome,
    TranscriptResult,
    TranscriptSegment,
    fetch_transcript,
    get_transcript,
)


# --- 테스트용 provider 팩토리 -------------------------------------------------


def _ok_attempt_provider(source: str):
    def provider(video_id):
        result = TranscriptResult(
            video_id=video_id,
            source=source,
            language="ko",
            segments=[
                TranscriptSegment(start=5.0, text="안녕하세요"),
                TranscriptSegment(start=65.0, text="여기는 제주"),
            ],
        )
        return TranscriptAttempt(
            provider=transcript._canonical_provider(source),
            outcome="success",
            result=result,
            language="ko",
        )

    return provider


def _fail_attempt_provider(provider_name: str, code: str):
    def provider(video_id):
        return TranscriptAttempt(provider=provider_name, outcome=code, detail=code)

    return provider


# --- TranscriptResult 직렬화(후보 timestamp 원천) 회귀 ------------------------


def test_transcript_result_text_and_timestamps():
    r = TranscriptResult(
        video_id="v",
        source="transcript_api",
        segments=[TranscriptSegment(0.0, "a"), TranscriptSegment(75.0, "b")],
    )
    assert r.text == "a\nb"
    assert r.to_timestamped_text() == "[00:00] a\n[01:15] b"


def test_success_preserves_segments_and_timestamps():
    outcome = fetch_transcript("vid", providers=(_ok_attempt_provider("transcript_api"),))
    assert outcome.succeeded
    assert outcome.result is not None
    # segments·to_timestamped_text가 평문화 없이 보존돼야 한다(후보 timestamp_start 원천).
    assert outcome.result.to_timestamped_text() == "[00:05] 안녕하세요\n[01:05] 여기는 제주"
    assert outcome.result.text == "안녕하세요\n여기는 제주"


# --- 체인: 첫 성공·폴백·전부 실패 --------------------------------------------


def test_fetch_transcript_uses_first_success_and_records_prior_failures():
    outcome = fetch_transcript(
        "vid",
        providers=(
            _fail_attempt_provider("youtube_transcript_api", "blocked"),
            _ok_attempt_provider("yt-dlp"),
        ),
    )
    assert outcome.succeeded
    assert outcome.result.source == "yt-dlp"
    # 성공 전 실패 시도까지 순서대로 보존한다.
    assert [a.outcome for a in outcome.attempts] == ["blocked", "success"]
    assert [a.sequence for a in outcome.attempts] == [1, 2]
    assert outcome.success_provider == "yt_dlp"
    assert outcome.failure_code is None


def test_fetch_transcript_all_fail_collects_codes():
    outcome = fetch_transcript(
        "vid",
        providers=(
            _fail_attempt_provider("youtube_transcript_api", "rate_limited"),
            _fail_attempt_provider("yt_dlp", "no_captions"),
        ),
    )
    assert not outcome.succeeded
    assert outcome.result is None
    assert [a.outcome for a in outcome.attempts] == ["rate_limited", "no_captions"]
    # 최종 실패 대표 코드 = 마지막으로 시도된 provider의 실패 코드.
    assert outcome.failure_code == "no_captions"
    assert outcome.success_provider is None


def test_run_provider_classifies_raised_exception():
    def raiser(video_id):
        raise RuntimeError("429 rate limit hit")

    outcome = fetch_transcript("vid", providers=(raiser,))
    assert outcome.attempts[0].outcome == "rate_limited"
    assert "RuntimeError" in (outcome.attempts[0].detail or "")


# --- 구 계약(TranscriptResult|None) coercion ---------------------------------


def test_chain_coerces_legacy_result_and_none_providers():
    def legacy_none(video_id):
        return None

    def legacy_ok(video_id):
        return TranscriptResult(
            video_id=video_id, source="yt-dlp", segments=[TranscriptSegment(0.0, "a")]
        )

    outcome = fetch_transcript("vid", providers=(legacy_none, legacy_ok))
    assert outcome.result is not None and outcome.result.source == "yt-dlp"
    assert outcome.attempts[0].outcome == "no_captions"
    assert outcome.attempts[1].outcome == "success"
    assert outcome.attempts[1].provider == "yt_dlp"


def test_outcome_coerce_classmethod():
    assert TranscriptOutcome.coerce(None).result is None
    assert TranscriptOutcome.coerce(None).attempts == []
    r = TranscriptResult(
        video_id="v", source="whisper", segments=[TranscriptSegment(0.0, "a")]
    )
    o = TranscriptOutcome.coerce(r)
    assert o.result is r
    assert o.success_provider == "whisper"
    existing = TranscriptOutcome(result=None, attempts=[])
    assert TranscriptOutcome.coerce(existing) is existing


# --- 얇은 result-only 래퍼 (하위 호환) ---------------------------------------


def test_get_transcript_returns_result_only():
    r = get_transcript("vid", providers=(_ok_attempt_provider("transcript_api"),))
    assert r is not None and r.source == "transcript_api"
    assert get_transcript("vid", providers=(_fail_attempt_provider("yt_dlp", "no_captions"),)) is None


async def test_get_transcript_async_wrapper():
    r = await transcript.get_transcript_async(
        "vid", providers=(_ok_attempt_provider("transcript_api"),)
    )
    assert r is not None and r.source == "transcript_api"


async def test_fetch_transcript_async_wrapper():
    outcome = await transcript.fetch_transcript_async(
        "vid", providers=(_ok_attempt_provider("yt-dlp"),)
    )
    assert outcome.succeeded and outcome.result.source == "yt-dlp"


# --- provider order 설정 연결(사문화 해소) -----------------------------------


def test_resolve_provider_chain_orders_by_config():
    chain = transcript.resolve_provider_chain(
        ["faster-whisper", "yt-dlp", "youtube-transcript-api"]
    )
    assert chain == (
        transcript.transcribe_via_whisper,
        transcript.fetch_via_ytdlp,
        transcript.fetch_via_transcript_api,
    )


def test_resolve_provider_chain_default_order():
    chain = transcript.resolve_provider_chain(
        ["youtube-transcript-api", "yt-dlp", "faster-whisper"]
    )
    assert chain == transcript.DEFAULT_PROVIDERS


def test_resolve_provider_chain_dedupes_and_falls_back():
    assert transcript.resolve_provider_chain([]) == transcript.DEFAULT_PROVIDERS
    assert transcript.resolve_provider_chain(["bogus"]) == transcript.DEFAULT_PROVIDERS
    # 중복 토큰은 한 번만.
    assert transcript.resolve_provider_chain(["yt-dlp", "yt_dlp"]) == (
        transcript.fetch_via_ytdlp,
    )


def test_settings_default_order_connects_to_real_chain():
    """`TRANSCRIPT_PROVIDER_ORDER` 기본값이 실제 provider 함수 체인으로 해석된다."""
    from ktc.core.config import Settings

    order = Settings().transcript_provider_order
    assert transcript.resolve_provider_chain(order) == transcript.DEFAULT_PROVIDERS


# --- provider 실패 코드 매핑 (mock 라이브러리) -------------------------------


def _install_fake_transcript_api(monkeypatch, exc):
    class _Api:  # get_transcript 없음 → 인스턴스 .fetch 경로.
        def fetch(self, video_id, languages=None):
            raise exc

    mod = types.ModuleType("youtube_transcript_api")
    mod.YouTubeTranscriptApi = _Api
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", mod)


def test_transcript_api_classifies_rate_limited(monkeypatch):
    class TooManyRequests(Exception):
        pass

    _install_fake_transcript_api(monkeypatch, TooManyRequests("429 Too Many Requests"))
    attempt = transcript.fetch_via_transcript_api("vid")
    assert attempt.provider == "youtube_transcript_api"
    assert attempt.outcome == "rate_limited"
    assert attempt.result is None
    assert "TooManyRequests" in (attempt.detail or "")


def test_transcript_api_classifies_blocked(monkeypatch):
    class IpBlocked(Exception):
        pass

    _install_fake_transcript_api(monkeypatch, IpBlocked("RequestBlocked: IP blocked by YouTube"))
    attempt = transcript.fetch_via_transcript_api("vid")
    assert attempt.outcome == "blocked"


def test_transcript_api_classifies_no_captions(monkeypatch):
    class TranscriptsDisabled(Exception):
        pass

    _install_fake_transcript_api(monkeypatch, TranscriptsDisabled("Subtitles are disabled"))
    attempt = transcript.fetch_via_transcript_api("vid")
    assert attempt.outcome == "no_captions"


def test_transcript_api_classifies_unknown_as_parse_error(monkeypatch):
    class WeirdError(Exception):
        pass

    _install_fake_transcript_api(monkeypatch, WeirdError("something unexpected"))
    attempt = transcript.fetch_via_transcript_api("vid")
    assert attempt.outcome == "parse_error"
    assert "WeirdError" in (attempt.detail or "")


def test_transcript_api_empty_is_no_captions(monkeypatch):
    class _Fetched:
        def to_raw_data(self):
            return []

    class _Api:
        def fetch(self, video_id, languages=None):
            return _Fetched()

    mod = types.ModuleType("youtube_transcript_api")
    mod.YouTubeTranscriptApi = _Api
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", mod)

    attempt = transcript.fetch_via_transcript_api("vid")
    assert attempt.outcome == "no_captions"


def test_fetch_via_transcript_api_supports_new_instance_api(monkeypatch):
    """youtube-transcript-api 1.x(.fetch) 성공 경로(이슈 #76)."""

    class _Fetched:
        def to_raw_data(self):
            return [
                {"start": 0.0, "text": "제주 카멜리아힐"},
                {"start": 12.0, "text": "수국 명소"},
            ]

    class _NewApi:  # get_transcript 없음 → 신 API 경로.
        def fetch(self, video_id, languages=None):
            return _Fetched()

    mod = types.ModuleType("youtube_transcript_api")
    mod.YouTubeTranscriptApi = _NewApi
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", mod)

    attempt = transcript.fetch_via_transcript_api("vid")
    assert attempt.outcome == "success"
    assert attempt.provider == "youtube_transcript_api"
    assert attempt.result is not None
    assert attempt.result.source == "transcript_api"
    assert [s.text for s in attempt.result.segments] == ["제주 카멜리아힐", "수국 명소"]
    assert attempt.result.segments[1].start == 12.0
    assert attempt.language == "ko"


# --- yt-dlp: 실제 언어 기록(D7) + download_error 분류 ------------------------


def _install_fake_ytdlp(monkeypatch, *, on_download):
    class _FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            on_download(self.opts)

    mod = types.ModuleType("yt_dlp")
    mod.YoutubeDL = _FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", mod)


def test_ytdlp_records_actual_track_language(monkeypatch):
    """요청 언어(ko)가 아니라 실제 내려받은 트랙 언어(en)를 기록한다(D7 수정)."""

    def write_english_vtt(opts):
        out_dir = Path(opts["outtmpl"]).parent
        (out_dir / "video.en.vtt").write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhello there\n",
            encoding="utf-8",
        )

    _install_fake_ytdlp(monkeypatch, on_download=write_english_vtt)
    attempt = transcript.fetch_via_ytdlp("video", languages=("ko", "en"))
    assert attempt.outcome == "success"
    assert attempt.provider == "yt_dlp"
    assert attempt.language == "en"  # ko 아님
    assert attempt.result is not None
    assert attempt.result.language == "en"
    assert attempt.result.segments[0].text == "hello there"


def test_ytdlp_no_file_is_no_captions(monkeypatch):
    _install_fake_ytdlp(monkeypatch, on_download=lambda opts: None)
    attempt = transcript.fetch_via_ytdlp("video")
    assert attempt.outcome == "no_captions"


def test_ytdlp_download_error_classified(monkeypatch):
    class DownloadError(Exception):
        pass

    def boom(opts):
        raise DownloadError("Unable to download webpage: timed out")

    _install_fake_ytdlp(monkeypatch, on_download=boom)
    attempt = transcript.fetch_via_ytdlp("video")
    assert attempt.outcome == "download_error"


def test_language_from_vtt_filename():
    assert transcript._language_from_vtt_filename(Path("abc.en.vtt")) == "en"
    assert transcript._language_from_vtt_filename(Path("abc.ko.vtt")) == "ko"
    assert transcript._language_from_vtt_filename(Path("abc.en-US.vtt")) == "en-US"
    assert transcript._language_from_vtt_filename(Path("abc.vtt")) is None


# --- whisper: env 게이트(disabled) / 미설치(not_configured) ------------------


def test_whisper_disabled_without_env(monkeypatch):
    monkeypatch.delenv("TRANSCRIPT_WHISPER_ENABLED", raising=False)
    attempt = transcript.transcribe_via_whisper("vid")
    assert attempt.outcome == "disabled"
    assert attempt.provider == "whisper"


def test_whisper_not_configured_with_env_but_no_libs(monkeypatch):
    monkeypatch.setenv("TRANSCRIPT_WHISPER_ENABLED", "1")
    attempt = transcript.transcribe_via_whisper("vid")
    assert attempt.outcome == "not_configured"


# --- 라이브러리 미설치 시 not_configured(graceful) --------------------------


def test_providers_not_configured_without_libs():
    # 테스트 환경에는 transcript 라이브러리가 없다 → 지연 import ImportError → not_configured.
    assert transcript.fetch_via_transcript_api("vid").outcome == "not_configured"
    assert transcript.fetch_via_ytdlp("vid").outcome == "not_configured"


# --- VTT 파서 회귀 -----------------------------------------------------------


def test_parse_vtt_extracts_segments_strips_tags_and_dedupes():
    vtt = (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "안녕하세요 제주입니다\n\n"
        "00:00:03.000 --> 00:00:05.000\n"
        "안녕하세요 제주입니다\n\n"
        "00:00:05.500 --> 00:00:08.000\n"
        "<c>카멜리아힐</c>에 왔어요\n"
    )
    segs = transcript._parse_vtt(vtt)
    assert len(segs) == 2  # 연속 중복 cue 병합
    assert segs[0].start == 1.0
    assert segs[0].text == "안녕하세요 제주입니다"
    assert segs[1].start == 5.5
    assert segs[1].text == "카멜리아힐에 왔어요"  # 인라인 태그 제거

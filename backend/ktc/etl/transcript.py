"""자막·전사 추출 provider 체인.

타인 영상 자막은 공식 captions API로 받을 수 없으므로 이 구간에만 비공식 의존을
허용한다(`docs/architecture.md` 4.3, ADR-9).

폴백 순서:
    1. youtube-transcript-api (수동/자동 자막)
    2. yt-dlp (--write-auto-sub / --write-subs)
    3. faster-whisper (로컬 전사)

각 provider는 사용 시점에만 지연 import하므로, 라이브러리가 없는 환경에서도 이
모듈을 import하고 테스트할 수 있다. 블로킹 호출은 `asyncio.to_thread`로 격리한다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class TranscriptSegment:
    start: float
    text: str


@dataclass
class TranscriptResult:
    """확보한 자막/전사 결과."""

    video_id: str
    source: str  # transcript_api | yt-dlp | whisper
    language: str | None = None
    segments: list[TranscriptSegment] = field(default_factory=list)

    @property
    def text(self) -> str:
        """타임스탬프를 제외한 전체 텍스트."""
        return "\n".join(seg.text for seg in self.segments)

    def to_timestamped_text(self) -> str:
        """`[mm:ss] 텍스트` 형태로 직렬화한다 (Gemini 입력용)."""
        lines = []
        for seg in self.segments:
            mm, ss = divmod(int(seg.start), 60)
            lines.append(f"[{mm:02d}:{ss:02d}] {seg.text}")
        return "\n".join(lines)


# provider 시그니처: (video_id) -> TranscriptResult | None
TranscriptProvider = Callable[[str], "TranscriptResult | None"]


def fetch_via_transcript_api(
    video_id: str, *, languages: tuple[str, ...] = ("ko", "en")
) -> TranscriptResult | None:
    """youtube-transcript-api로 자막을 확보한다 (지연 import).

    youtube-transcript-api 1.x는 정적 `get_transcript`를 제거하고 인스턴스
    `fetch`로 바꿨다. 두 API를 모두 지원한다(구버전 우선 호환).
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except ImportError:
        return None
    try:
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            # 구버전(<1.0) 정적 API
            raw = YouTubeTranscriptApi.get_transcript(  # type: ignore[attr-defined]
                video_id, languages=list(languages)
            )
        else:
            # 신버전(>=1.0) 인스턴스 API: fetch() → FetchedTranscript
            fetched = YouTubeTranscriptApi().fetch(video_id, languages=list(languages))
            if hasattr(fetched, "to_raw_data"):
                raw = fetched.to_raw_data()
            else:
                raw = [
                    {
                        "start": getattr(snippet, "start", 0.0),
                        "text": getattr(snippet, "text", ""),
                    }
                    for snippet in fetched
                ]
    except Exception:
        return None
    segments = [
        TranscriptSegment(start=float(item.get("start", 0.0)), text=item.get("text", ""))
        for item in raw
    ]
    if not segments:
        return None
    return TranscriptResult(
        video_id=video_id, source="transcript_api", language=languages[0], segments=segments
    )


def _parse_vtt(content: str) -> list[TranscriptSegment]:
    """WebVTT 자막 텍스트를 TranscriptSegment 리스트로 파싱한다.

    cue 시작 시각과 텍스트를 모으고, 인라인 태그(`<...>`)를 제거하며, 자동 자막의
    연속 중복 라인을 합친다.
    """
    import re

    tag_re = re.compile(r"<[^>]+>")
    time_re = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->")
    segments: list[TranscriptSegment] = []
    start: float | None = None
    texts: list[str] = []

    def commit() -> None:
        nonlocal start, texts
        if start is not None:
            joined = " ".join(
                t for t in (tag_re.sub("", x).strip() for x in texts) if t
            )
            if joined:
                segments.append(TranscriptSegment(start=start, text=joined))
        start, texts = None, []

    for raw in content.splitlines():
        line = raw.rstrip()
        match = time_re.search(line)
        if match:
            commit()
            h, mi, s, ms = (int(match.group(i)) for i in range(1, 5))
            start = h * 3600 + mi * 60 + s + ms / 1000.0
            texts = []
        elif start is not None:
            stripped = line.strip()
            if stripped == "":
                commit()
            elif stripped != "WEBVTT" and not stripped.isdigit():
                texts.append(line)
    commit()

    deduped: list[TranscriptSegment] = []
    for seg in segments:
        if deduped and deduped[-1].text == seg.text:
            continue
        deduped.append(seg)
    return deduped


def fetch_via_ytdlp(
    video_id: str, *, languages: tuple[str, ...] = ("ko", "en")
) -> TranscriptResult | None:
    """yt-dlp로 자막(수동/자동)을 내려받아 파싱하는 폴백 (지연 import).

    youtube-transcript-api가 막히거나 형식이 바뀌어도 yt-dlp는 자동 자막을 받을 수
    있는 경우가 많다. 자막이 비활성화된 영상은 None.
    """
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        return None
    import tempfile
    from pathlib import Path

    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmp:
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": list(languages),
            "subtitlesformat": "vtt",
            "outtmpl": str(Path(tmp) / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception:
            return None
        vtt_path: "Path | None" = None
        for lang in languages:
            matches = sorted(Path(tmp).glob(f"*.{lang}*.vtt"))
            if matches:
                vtt_path = matches[0]
                break
        if vtt_path is None:
            any_vtt = sorted(Path(tmp).glob("*.vtt"))
            vtt_path = any_vtt[0] if any_vtt else None
        if vtt_path is None:
            return None
        segments = _parse_vtt(vtt_path.read_text(encoding="utf-8", errors="ignore"))
    if not segments:
        return None
    return TranscriptResult(
        video_id=video_id, source="yt-dlp", language=languages[0], segments=segments
    )


def transcribe_via_whisper(
    video_id: str, *, languages: tuple[str, ...] = ("ko", "en")
) -> TranscriptResult | None:
    """faster-whisper 로컬 전사 최종 폴백 (지연 import, 환경 플래그로 opt-in).

    오디오 다운로드(yt-dlp)와 전사(faster-whisper)는 CPU 집약·블로킹·모델 다운로드를
    수반하므로 기본 비활성(`TRANSCRIPT_WHISPER_ENABLED`)으로 둔다. 자막이 없는
    영상까지 커버하려면 운영에서 명시적으로 켠다.
    """
    import os

    if os.getenv("TRANSCRIPT_WHISPER_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return None
    try:
        import yt_dlp  # type: ignore
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return None
    import tempfile
    from pathlib import Path

    url = f"https://www.youtube.com/watch?v={video_id}"
    model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
    segments: list[TranscriptSegment] = []
    with tempfile.TemporaryDirectory() as tmp:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": str(Path(tmp) / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}
            ],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception:
            return None
        audio = next(iter(sorted(Path(tmp).glob("*.mp3"))), None) or next(
            iter(sorted(Path(tmp).glob("*"))), None
        )
        if audio is None:
            return None
        try:
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            whisper_segments, _info = model.transcribe(str(audio))
            segments = [
                TranscriptSegment(start=float(seg.start), text=seg.text.strip())
                for seg in whisper_segments
                if seg.text and seg.text.strip()
            ]
        except Exception:
            return None
    if not segments:
        return None
    return TranscriptResult(
        video_id=video_id, source="whisper", language=languages[0], segments=segments
    )


# 기본 폴백 체인
DEFAULT_PROVIDERS: tuple[TranscriptProvider, ...] = (
    fetch_via_transcript_api,
    fetch_via_ytdlp,
    transcribe_via_whisper,
)


def get_transcript(
    video_id: str, *, providers: tuple[TranscriptProvider, ...] | None = None
) -> TranscriptResult | None:
    """provider 체인을 순서대로 시도해 첫 성공 결과를 반환한다."""
    for provider in providers or DEFAULT_PROVIDERS:
        result = provider(video_id)
        if result is not None and result.segments:
            return result
    return None


async def get_transcript_async(
    video_id: str, *, providers: tuple[TranscriptProvider, ...] | None = None
) -> TranscriptResult | None:
    """블로킹 provider 체인을 executor로 격리해 실행한다."""
    return await asyncio.to_thread(get_transcript, video_id, providers=providers)

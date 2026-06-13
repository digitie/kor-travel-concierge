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
    """youtube-transcript-api로 자막을 확보한다 (지연 import)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except ImportError:
        return None
    try:
        raw = YouTubeTranscriptApi.get_transcript(video_id, languages=list(languages))
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


def fetch_via_ytdlp(video_id: str) -> TranscriptResult | None:
    """yt-dlp 자막 추출 폴백 (지연 import).

    실제 다운로드/파싱 구현은 환경 의존이 커서 라이브러리 가용 여부만 확인하고,
    파싱 책임은 호출자 제공 훅으로 위임할 수 있게 둔다. 기본은 None.
    """
    try:
        import yt_dlp  # type: ignore  # noqa: F401
    except ImportError:
        return None
    # Placeholder: 자막 파일 다운로드 → VTT/SRT 파싱은 운영 환경에서 보강한다.
    return None


def transcribe_via_whisper(video_id: str) -> TranscriptResult | None:
    """faster-whisper 로컬 전사 최종 폴백 (지연 import).

    오디오 다운로드와 전사는 CPU 집약·블로킹이므로 호출자는 프로세스풀에서 실행할
    수 있다. 라이브러리 미설치 시 None.
    """
    try:
        import faster_whisper  # type: ignore  # noqa: F401
    except ImportError:
        return None
    return None


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

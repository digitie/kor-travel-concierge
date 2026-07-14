"""자막·전사 추출 provider 체인 (T-164 재설계, 로드맵 PR-11 개정판, G7).

타인 영상 자막은 공식 captions API로 받을 수 없으므로 이 구간에만 비공식 의존을
허용한다(`docs/architecture.md` 4.3, ADR-9).

폴백 순서(`TRANSCRIPT_PROVIDER_ORDER` 설정으로 조정 — T-164에서 실제 체인에 연결):
    1. youtube-transcript-api (수동/자동 자막)
    2. yt-dlp (--write-auto-sub / --write-subs)
    3. faster-whisper (로컬 전사)

각 provider는 사용 시점에만 지연 import하므로, 라이브러리가 없는 환경에서도 이
모듈을 import하고 테스트할 수 있다. 블로킹 호출은 `asyncio.to_thread`로 격리한다.

**관측(T-164)**: 각 provider의 시도는 `except Exception: return None`으로 삼키지 않고
예외 유형별 `TranscriptOutcomeCode`로 분류해 `TranscriptAttempt`로 반환한다(예외를
삼키되 **분류해서** 삼킨다). 체인은 성공 전 실패 시도까지 모두 `TranscriptOutcome`에
모아 반환하며, 성공 시 기존 `TranscriptResult`(segments·`to_timestamped_text()` — 후보
`timestamp_start`의 원천)를 그대로 wrap한다. 상위 배선이 이 attempts를
`transcript_attempts` 테이블에 durable하게 기록한다.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


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


class TranscriptProviderName(str, Enum):
    """`transcript_attempts.provider`의 canonical 값(G7 선별 쿼리 기준)."""

    YOUTUBE_TRANSCRIPT_API = "youtube_transcript_api"
    YT_DLP = "yt_dlp"
    WHISPER = "whisper"


class TranscriptOutcomeCode(str, Enum):
    """provider 시도 1건의 결과. 성공(success) + 실패 사유 코드(D1 소실 해소)."""

    SUCCESS = "success"
    # 영상에 자막이 없음/업로더가 비활성/미제공(빈 자막 포함).
    NO_CAPTIONS = "no_captions"
    # IP·요청 차단(403/봇 탐지 등).
    BLOCKED = "blocked"
    # 429/요청 과다.
    RATE_LIMITED = "rate_limited"
    # 네트워크·다운로드 실패.
    DOWNLOAD_ERROR = "download_error"
    # 파싱/분류 불가한 알 수 없는 예외(detail 보존).
    PARSE_ERROR = "parse_error"
    # provider가 설정상 비활성(예: whisper env off).
    DISABLED = "disabled"
    # provider 라이브러리 미설치/미구성.
    NOT_CONFIGURED = "not_configured"


# 실패로 분류되는(=성공이 아닌) outcome 집합.
_FAILURE_CODES = frozenset(
    c.value for c in TranscriptOutcomeCode if c is not TranscriptOutcomeCode.SUCCESS
)

# 요약 캐시 대표 실패 코드의 우선순위(영상 자체에 대한 정보량이 큰 것부터).
# no_captions(진짜 자막 없음)를 최우선으로 노출해 T-169 "자막 비활성 확정 영상"
# 선별에 쓴다. disabled/not_configured는 provider 쪽 사정이라 최하위로 둔다.
_FAILURE_PRIORITY = (
    TranscriptOutcomeCode.NO_CAPTIONS.value,
    TranscriptOutcomeCode.BLOCKED.value,
    TranscriptOutcomeCode.RATE_LIMITED.value,
    TranscriptOutcomeCode.DOWNLOAD_ERROR.value,
    TranscriptOutcomeCode.PARSE_ERROR.value,
    TranscriptOutcomeCode.DISABLED.value,
    TranscriptOutcomeCode.NOT_CONFIGURED.value,
)


@dataclass
class TranscriptAttempt:
    """provider 1회 시도의 관측 레코드(성공 전 실패도 보존)."""

    provider: str  # TranscriptProviderName 값
    outcome: str  # TranscriptOutcomeCode 값
    sequence: int = 0  # 체인 내 시도 순서(1부터). 체인이 채운다.
    # 성공 시에만 채워지는 실제 결과(DB에는 저장하지 않는다 — segments 원천 보존용).
    result: TranscriptResult | None = None
    language: str | None = None
    detail: str | None = None
    duration_ms: int | None = None
    tool_version: str | None = None

    @property
    def succeeded(self) -> bool:
        return (
            self.outcome == TranscriptOutcomeCode.SUCCESS.value
            and self.result is not None
        )


@dataclass
class TranscriptOutcome:
    """체인 실행 결과: 성공 result(있으면) + 모든 시도 목록."""

    result: TranscriptResult | None
    attempts: list[TranscriptAttempt] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.result is not None

    @property
    def success_provider(self) -> str | None:
        """성공 provider(canonical). 요약 캐시 `transcript_source`의 원천."""
        for attempt in self.attempts:
            if attempt.succeeded:
                return attempt.provider
        if self.result is not None:
            return canonical_provider(self.result.source)
        return None

    @property
    def failure_code(self) -> str | None:
        """전 provider 실패 시 대표 코드(성공이면 None). 요약 캐시의 원천.

        시도된 실패 코드 중 영상에 대한 정보량이 큰 것(`_FAILURE_PRIORITY`)을 고른다.
        예: youtube_transcript_api=blocked → yt_dlp=no_captions → whisper=disabled면
        `no_captions`를 대표로 삼아 T-169 "자막 비활성 확정 영상" 선별을 가능케 한다
        (마지막 provider의 disabled로 신호가 가려지지 않도록).
        """
        if self.result is not None:
            return None
        present = {a.outcome for a in self.attempts if a.outcome in _FAILURE_CODES}
        for code in _FAILURE_PRIORITY:
            if code in present:
                return code
        return None

    @classmethod
    def coerce(cls, value: object) -> "TranscriptOutcome":
        """레거시/외부 fetcher 반환값을 TranscriptOutcome으로 정규화한다.

        `TranscriptOutcome`은 그대로, `TranscriptResult`는 성공 1건으로, `None`은
        빈 실패로 감싼다. 주입형 fetcher가 구 계약(TranscriptResult|None)을 반환해도
        상위 배선이 동일하게 처리하도록 한다.
        """
        if isinstance(value, TranscriptOutcome):
            return value
        if value is None:
            return cls(result=None, attempts=[])
        if isinstance(value, TranscriptResult):
            # segments가 없으면 성공으로 단락하지 않는다 — transcript_source=provider인데
            # crawl_status=FAILED·failure_code=None인 불일치 캐시를 막는다(리뷰 MINOR-1).
            if not value.segments:
                return cls(
                    result=None,
                    attempts=[
                        TranscriptAttempt(
                            provider=canonical_provider(value.source),
                            outcome=TranscriptOutcomeCode.NO_CAPTIONS.value,
                            sequence=1,
                            language=value.language,
                            detail="빈 자막(segments 없음)",
                        )
                    ],
                )
            attempt = TranscriptAttempt(
                provider=canonical_provider(value.source),
                outcome=TranscriptOutcomeCode.SUCCESS.value,
                sequence=1,
                result=value,
                language=value.language,
            )
            return cls(result=value, attempts=[attempt])
        raise TypeError(f"TranscriptOutcome으로 변환할 수 없는 값: {type(value)!r}")


# provider 시그니처: (video_id) -> TranscriptAttempt (레거시 TranscriptResult|None도 허용)
TranscriptProvider = Callable[[str], "TranscriptAttempt | TranscriptResult | None"]


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _exc_detail(exc: BaseException) -> str:
    """예외를 분류 후에도 진단 가능하도록 유형+메시지를 보존한다(길이 상한)."""
    message = str(exc).strip()
    label = type(exc).__name__
    text = f"{label}: {message}" if message else label
    return text[:2000]


def _dist_version(dist_name: str) -> str | None:
    """설치된 배포 버전(관측용). 미설치/조회 실패는 None."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version(dist_name)[:32]
        except PackageNotFoundError:
            return None
    except Exception:  # pragma: no cover - 방어적
        return None


def _classify_exception(exc: BaseException) -> str:
    """provider 예외를 `TranscriptOutcomeCode` 값으로 분류한다.

    라이브러리별 예외 클래스를 직접 import하지 않고(버전별 상이) 클래스명+메시지
    heuristic으로 분류한다. 알 수 없는 예외는 `parse_error`로 두고 detail을 보존한다.
    """
    haystack = f"{type(exc).__name__} {exc}".lower()

    def has(*needles: str) -> bool:
        return any(n in haystack for n in needles)

    # 자막 자체가 없음/비활성/영상 접근 불가(자막을 얻을 수 없는 상태).
    if has(
        "transcriptsdisabled",
        "notranscriptfound",
        "no transcript",
        "notranslatable",
        "subtitles are disabled",
        "no subtitle",
        "no closed captions",
    ):
        return TranscriptOutcomeCode.NO_CAPTIONS.value
    # 429/요청 과다(차단보다 먼저 판정).
    if has("toomanyrequests", "429", "too many requests", "rate limit", "ratelimit"):
        return TranscriptOutcomeCode.RATE_LIMITED.value
    # IP/요청 차단, 봇 탐지, 403.
    if has(
        "ipblocked",
        "requestblocked",
        "blocked",
        "403",
        "forbidden",
        "sign in to confirm",
        "confirm you're not a bot",
        "captcha",
    ):
        return TranscriptOutcomeCode.BLOCKED.value
    # 영상 자체가 없음/비공개/삭제/회원 전용 → 자막 확보 불가.
    if has(
        "videounavailable",
        "video unavailable",
        "unavailable",
        "private video",
        "has been removed",
        "members-only",
        "age restricted",
        "age-restricted",
    ):
        return TranscriptOutcomeCode.NO_CAPTIONS.value
    # 네트워크/다운로드 실패.
    if has(
        "downloaderror",
        "http error",
        "httperror",
        "timeout",
        "timed out",
        "connection",
        "network",
        "unable to download",
        "urlerror",
        "ssl",
        "resolve",
    ):
        return TranscriptOutcomeCode.DOWNLOAD_ERROR.value
    return TranscriptOutcomeCode.PARSE_ERROR.value


def _classify_captured_error_text(text: str) -> str | None:
    """yt-dlp가 `ignoreerrors`로 삼킨 뒤 로거에 남긴 에러 문자열에서 **명확한** 실패
    신호(blocked/rate_limited/download_error)만 뽑는다(리뷰 MAJOR).

    자막 미제공(no_captions)과 구분해야 하므로, 위 세 코드가 아니면 None을 반환해
    호출자가 no_captions 기본값을 유지하게 한다(benign 경고를 실패로 오분류 금지).
    """
    if not text or not text.strip():
        return None
    code = _classify_exception(RuntimeError(text))
    if code in (
        TranscriptOutcomeCode.BLOCKED.value,
        TranscriptOutcomeCode.RATE_LIMITED.value,
        TranscriptOutcomeCode.DOWNLOAD_ERROR.value,
    ):
        return code
    return None


class _YtdlpErrorCollector:
    """yt-dlp `logger` 주입용 — error/warning 메시지를 모은다(분류 원천).

    `ignoreerrors=True`가 아니어도 yt-dlp는 일부 실패를 예외 없이 로깅만 하고 넘어갈 수
    있어(자막 부분 실패 등), 예외 경로와 별개로 캡처 로그가 필요하다.
    """

    def __init__(self) -> None:
        self.messages: list[str] = []

    def debug(self, msg: object) -> None:  # noqa: D401 - yt-dlp logger 계약
        # yt-dlp는 info도 debug로 보내며 접두사 '[debug]'로 구분한다. 잡음 무시.
        text = str(msg)
        if text.startswith("ERROR:") or text.startswith("WARNING:"):
            self.messages.append(text)

    def info(self, msg: object) -> None:
        pass

    def warning(self, msg: object) -> None:
        self.messages.append(str(msg))

    def error(self, msg: object) -> None:
        self.messages.append(str(msg))

    def captured(self) -> str:
        return " ".join(self.messages)


def canonical_provider(source: str | None) -> str:
    """`TranscriptResult.source`(레거시 표기)를 canonical provider 값으로 매핑."""
    mapping = {
        "transcript_api": TranscriptProviderName.YOUTUBE_TRANSCRIPT_API.value,
        "youtube_transcript_api": TranscriptProviderName.YOUTUBE_TRANSCRIPT_API.value,
        "yt-dlp": TranscriptProviderName.YT_DLP.value,
        "yt_dlp": TranscriptProviderName.YT_DLP.value,
        "whisper": TranscriptProviderName.WHISPER.value,
    }
    if source is None:
        return "unknown"
    return mapping.get(source, source[:24])


def _language_from_vtt_filename(path) -> str | None:
    """yt-dlp가 쓴 `<id>.<lang>.vtt` 파일명에서 실제 트랙 언어를 뽑는다(D7 수정).

    기존 코드는 요청 언어(`languages[0]`)를 무조건 기록해 임의 vtt 폴백 시 실제 언어를
    오기록했다. 파일명 마지막 dot-세그먼트가 언어 태그(`ko`, `en`, `en-US` 등)다.
    """
    name = path.name
    if name.lower().endswith(".vtt"):
        name = name[:-4]
    parts = name.split(".")
    if len(parts) >= 2:
        return parts[-1][:16] or None
    return None


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


def fetch_via_transcript_api(
    video_id: str, *, languages: tuple[str, ...] = ("ko", "en")
) -> TranscriptAttempt:
    """youtube-transcript-api로 자막을 확보한다 (지연 import).

    youtube-transcript-api 1.x는 정적 `get_transcript`를 제거하고 인스턴스
    `fetch`로 바꿨다. 두 API를 모두 지원한다(구버전 우선 호환).
    """
    started = time.monotonic()
    provider = TranscriptProviderName.YOUTUBE_TRANSCRIPT_API.value

    def done(
        outcome: str,
        *,
        result: TranscriptResult | None = None,
        language: str | None = None,
        detail: str | None = None,
    ) -> TranscriptAttempt:
        return TranscriptAttempt(
            provider=provider,
            outcome=outcome,
            result=result,
            language=language,
            detail=detail,
            duration_ms=_elapsed_ms(started),
            tool_version=_dist_version("youtube-transcript-api"),
        )

    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except ImportError:
        return done(
            TranscriptOutcomeCode.NOT_CONFIGURED.value,
            detail="youtube-transcript-api 미설치",
        )
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
    except Exception as exc:
        return done(_classify_exception(exc), detail=_exc_detail(exc))
    segments = [
        TranscriptSegment(start=float(item.get("start", 0.0)), text=item.get("text", ""))
        for item in raw
    ]
    if not segments:
        return done(TranscriptOutcomeCode.NO_CAPTIONS.value, detail="빈 자막")
    result = TranscriptResult(
        video_id=video_id, source="transcript_api", language=languages[0], segments=segments
    )
    return done(
        TranscriptOutcomeCode.SUCCESS.value, result=result, language=languages[0]
    )


def fetch_via_ytdlp(
    video_id: str, *, languages: tuple[str, ...] = ("ko", "en")
) -> TranscriptAttempt:
    """yt-dlp로 자막(수동/자동)을 내려받아 파싱하는 폴백 (지연 import).

    youtube-transcript-api가 막히거나 형식이 바뀌어도 yt-dlp는 자동 자막을 받을 수
    있는 경우가 많다. 자막이 비활성화된 영상은 no_captions.
    """
    started = time.monotonic()
    provider = TranscriptProviderName.YT_DLP.value

    def done(
        outcome: str,
        *,
        result: TranscriptResult | None = None,
        language: str | None = None,
        detail: str | None = None,
    ) -> TranscriptAttempt:
        return TranscriptAttempt(
            provider=provider,
            outcome=outcome,
            result=result,
            language=language,
            detail=detail,
            duration_ms=_elapsed_ms(started),
            tool_version=_dist_version("yt-dlp"),
        )

    try:
        import yt_dlp  # type: ignore
    except ImportError:
        return done(TranscriptOutcomeCode.NOT_CONFIGURED.value, detail="yt-dlp 미설치")
    import tempfile
    from pathlib import Path

    url = f"https://www.youtube.com/watch?v={video_id}"
    collector = _YtdlpErrorCollector()
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
            # 리뷰 MAJOR: ignoreerrors=True이면 yt-dlp가 차단·429·네트워크 실패의
            # DownloadError를 내부에서 삼켜 예외가 오지 않고 vtt만 없어 no_captions로
            # 오분류된다(T-169 "자막 비활성 확정" 선별 오염). False로 두어 실 예외를
            # _classify_exception에 닿게 하고, 그래도 삼켜지는 경우를 대비해 error
            # logger를 주입해 캡처 로그로 분류한다.
            "ignoreerrors": False,
            "logger": collector,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as exc:
            # 예외 메시지가 빈약하면(래핑 등) 캡처 로그로 보강해 분류한다.
            code = _classify_exception(exc)
            if code == TranscriptOutcomeCode.PARSE_ERROR.value:
                code = _classify_captured_error_text(collector.captured()) or code
            detail = _exc_detail(exc)
            captured = collector.captured()
            if captured and captured not in detail:
                detail = f"{detail} | log: {captured}"[:2000]
            return done(code, detail=detail)
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
            # 예외 없이 리턴했지만 vtt가 없다 → ignoreerrors 등으로 삼킨 실패일 수 있다.
            # 캡처된 에러 로그에 blocked/rate_limited/download_error 신호가 있으면 그로
            # 분류하고, 없으면 진짜 자막 미제공(no_captions)으로 둔다.
            captured = collector.captured()
            code = _classify_captured_error_text(captured)
            if code is not None:
                return done(code, detail=captured[:2000])
            return done(
                TranscriptOutcomeCode.NO_CAPTIONS.value,
                detail="자막 파일 없음(비활성/미제공)",
            )
        # D7 수정: 요청 언어가 아니라 실제 내려받은 트랙 언어를 기록한다.
        actual_language = _language_from_vtt_filename(vtt_path) or (
            languages[0] if languages else None
        )
        try:
            segments = _parse_vtt(vtt_path.read_text(encoding="utf-8", errors="ignore"))
        except Exception as exc:
            return done(TranscriptOutcomeCode.PARSE_ERROR.value, detail=_exc_detail(exc))
    if not segments:
        return done(TranscriptOutcomeCode.NO_CAPTIONS.value, detail="빈 자막")
    result = TranscriptResult(
        video_id=video_id, source="yt-dlp", language=actual_language, segments=segments
    )
    return done(
        TranscriptOutcomeCode.SUCCESS.value, result=result, language=actual_language
    )


def transcribe_via_whisper(
    video_id: str,
    *,
    languages: tuple[str, ...] = ("ko", "en"),
    force: bool = False,
    model_size: str | None = None,
) -> TranscriptAttempt:
    """faster-whisper 로컬 전사 최종 폴백 (지연 import, 환경 플래그로 opt-in).

    오디오 다운로드(yt-dlp)와 전사(faster-whisper)는 CPU 집약·블로킹·모델 다운로드를
    수반하므로 auto 폴백은 기본 비활성(`TRANSCRIPT_WHISPER_ENABLED`)으로 둔다. 자막이
    없는 영상까지 커버하려면 운영에서 명시적으로 켠다.

    `force=True`(T-169)면 운영자의 명시적 수동 재전사 경로라 `TRANSCRIPT_WHISPER_ENABLED`
    게이트를 우회해 실행한다. `force=False`(기본)일 때의 auto 동작은 그대로다 — 게이트가
    꺼져 있으면 여전히 `disabled`를 반환한다. `model_size`를 주면 env `WHISPER_MODEL_SIZE`
    대신 그 값을 쓴다.
    """
    import os

    started = time.monotonic()
    provider = TranscriptProviderName.WHISPER.value

    def done(
        outcome: str,
        *,
        result: TranscriptResult | None = None,
        language: str | None = None,
        detail: str | None = None,
    ) -> TranscriptAttempt:
        return TranscriptAttempt(
            provider=provider,
            outcome=outcome,
            result=result,
            language=language,
            detail=detail,
            duration_ms=_elapsed_ms(started),
            tool_version=_dist_version("faster-whisper"),
        )

    if not force and os.getenv("TRANSCRIPT_WHISPER_ENABLED", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return done(
            TranscriptOutcomeCode.DISABLED.value,
            detail="TRANSCRIPT_WHISPER_ENABLED 비활성",
        )
    try:
        import yt_dlp  # type: ignore
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return done(
            TranscriptOutcomeCode.NOT_CONFIGURED.value,
            detail="yt-dlp/faster-whisper 미설치",
        )
    import tempfile
    from pathlib import Path

    url = f"https://www.youtube.com/watch?v={video_id}"
    resolved_model_size = model_size or os.getenv("WHISPER_MODEL_SIZE", "base")
    segments: list[TranscriptSegment] = []
    detected_language: str | None = None
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
        except Exception as exc:
            return done(_classify_exception(exc), detail=_exc_detail(exc))
        audio = next(iter(sorted(Path(tmp).glob("*.mp3"))), None) or next(
            iter(sorted(Path(tmp).glob("*"))), None
        )
        if audio is None:
            return done(
                TranscriptOutcomeCode.DOWNLOAD_ERROR.value, detail="오디오 다운로드 실패"
            )
        try:
            model = WhisperModel(resolved_model_size, device="cpu", compute_type="int8")
            whisper_segments, info = model.transcribe(str(audio))
            detected_language = getattr(info, "language", None)
            segments = [
                TranscriptSegment(start=float(seg.start), text=seg.text.strip())
                for seg in whisper_segments
                if seg.text and seg.text.strip()
            ]
        except Exception as exc:
            return done(TranscriptOutcomeCode.PARSE_ERROR.value, detail=_exc_detail(exc))
    if not segments:
        return done(TranscriptOutcomeCode.NO_CAPTIONS.value, detail="전사 결과 없음")
    language = detected_language or languages[0]
    result = TranscriptResult(
        video_id=video_id, source="whisper", language=language, segments=segments
    )
    return done(TranscriptOutcomeCode.SUCCESS.value, result=result, language=language)


def whisper_forced_provider(model_size: str | None = None) -> TranscriptProvider:
    """게이트를 우회해 whisper로만 강제 전사하는 provider를 만든다(T-169 수동 재전사).

    체인 실행부(`_run_provider`)는 provider를 `fn(video_id)`로만 호출하므로 force·model을
    클로저로 고정한다. 반환 `TranscriptAttempt.provider`는 whisper라 관측·기록도 그대로다.
    """

    def _provider(video_id: str) -> TranscriptAttempt:
        return transcribe_via_whisper(video_id, force=True, model_size=model_size)

    _provider.__name__ = "transcribe_via_whisper_forced"
    return _provider


def whisper_forced_chain(
    model_size: str | None = None,
) -> tuple[TranscriptProvider, ...]:
    """whisper 강제 전사만 담은 단일-provider 체인(수동 재전사 fetcher 주입용)."""
    return (whisper_forced_provider(model_size),)


# 기본 폴백 체인(설정이 비었거나 해석 불가할 때).
DEFAULT_PROVIDERS: tuple[TranscriptProvider, ...] = (
    fetch_via_transcript_api,
    fetch_via_ytdlp,
    transcribe_via_whisper,
)

# 캡션 전용 체인(whisper 제외, T-172). fetch/whisper를 분리 병렬화하는 진입점의
# 기본값이다 — CPU 집약적인 whisper는 이 체인에 절대 섞이지 않는다.
CAPTION_PROVIDERS: tuple[TranscriptProvider, ...] = (
    fetch_via_transcript_api,
    fetch_via_ytdlp,
)

# 설정 토큰(`TRANSCRIPT_PROVIDER_ORDER`) → provider 함수. 하이픈/언더스코어/별칭 수용.
_PROVIDER_REGISTRY: dict[str, TranscriptProvider] = {
    "youtube-transcript-api": fetch_via_transcript_api,
    "youtube_transcript_api": fetch_via_transcript_api,
    "transcript_api": fetch_via_transcript_api,
    "transcript-api": fetch_via_transcript_api,
    "yt-dlp": fetch_via_ytdlp,
    "yt_dlp": fetch_via_ytdlp,
    "ytdlp": fetch_via_ytdlp,
    "faster-whisper": transcribe_via_whisper,
    "faster_whisper": transcribe_via_whisper,
    "whisper": transcribe_via_whisper,
}

# provider 함수 → canonical 라벨(레거시/None 반환 coercion 시 provider 이름 복원용).
_PROVIDER_LABELS: dict[TranscriptProvider, str] = {
    fetch_via_transcript_api: TranscriptProviderName.YOUTUBE_TRANSCRIPT_API.value,
    fetch_via_ytdlp: TranscriptProviderName.YT_DLP.value,
    transcribe_via_whisper: TranscriptProviderName.WHISPER.value,
}


def resolve_provider_chain(order: list[str]) -> tuple[TranscriptProvider, ...]:
    """설정 토큰 순서를 provider 함수 순서로 해석한다(사문화 해소, T-164 절차 4).

    미지의 토큰은 건너뛰고 중복은 제거한다. 유효 provider가 하나도 없으면
    `DEFAULT_PROVIDERS`로 폴백한다(설정 오타가 자막 확보를 통째로 막지 않도록).
    """
    resolved: list[TranscriptProvider] = []
    for token in order:
        fn = _PROVIDER_REGISTRY.get(token.strip().lower())
        if fn is not None and fn not in resolved:
            resolved.append(fn)
    return tuple(resolved) or DEFAULT_PROVIDERS


def _resolve_provider_chain() -> tuple[TranscriptProvider, ...]:
    """런타임 설정(`TRANSCRIPT_PROVIDER_ORDER`)으로 체인을 구성한다."""
    try:
        from ktc.core.config import get_settings

        order = get_settings().transcript_provider_order
    except Exception:
        order = []
    return resolve_provider_chain(order)


def caption_provider_chain() -> tuple[TranscriptProvider, ...]:
    """캡션 전용 체인(whisper 제외, T-172).

    설정 순서(`TRANSCRIPT_PROVIDER_ORDER`)를 존중하되 `transcribe_via_whisper`만
    제거한다. whisper는 CPU 집약이라 caption 병렬 fetch(Semaphore 다수)에 절대
    섞이면 안 되고, 항상 별도 동시성 1 경로(`transcribe_whisper_async`)로만 실행한다.
    제거 후 남는 provider가 없으면(설정이 whisper 하나만 지정 등) `CAPTION_PROVIDERS`
    기본값으로 폴백한다(캡션 확보가 통째로 막히지 않도록).
    """
    chain = tuple(
        fn for fn in _resolve_provider_chain() if fn is not transcribe_via_whisper
    )
    return chain or CAPTION_PROVIDERS


def _provider_label(fn: TranscriptProvider) -> str:
    return _PROVIDER_LABELS.get(fn) or getattr(fn, "__name__", "unknown")[:24]


def _run_provider(
    fn: TranscriptProvider, video_id: str, sequence: int
) -> TranscriptAttempt:
    started = time.monotonic()
    try:
        raw = fn(video_id)
    except Exception as exc:  # provider 함수가 직접 예외를 던져도 분류해 삼킨다.
        return TranscriptAttempt(
            provider=_provider_label(fn),
            outcome=_classify_exception(exc),
            sequence=sequence,
            detail=_exc_detail(exc),
            duration_ms=_elapsed_ms(started),
        )
    if isinstance(raw, TranscriptAttempt):
        raw.sequence = sequence
        if raw.duration_ms is None:
            raw.duration_ms = _elapsed_ms(started)
        return raw
    # 레거시 반환(TranscriptResult|None) coercion.
    # None 또는 segments 없는 결과는 no_captions(성공 단락 금지 — 리뷰 MINOR-1).
    if raw is None:
        return TranscriptAttempt(
            provider=_provider_label(fn),
            outcome=TranscriptOutcomeCode.NO_CAPTIONS.value,
            sequence=sequence,
            duration_ms=_elapsed_ms(started),
        )
    if not raw.segments:
        return TranscriptAttempt(
            provider=canonical_provider(raw.source),
            outcome=TranscriptOutcomeCode.NO_CAPTIONS.value,
            sequence=sequence,
            language=raw.language,
            detail="빈 자막(segments 없음)",
            duration_ms=_elapsed_ms(started),
        )
    return TranscriptAttempt(
        provider=canonical_provider(raw.source),
        outcome=TranscriptOutcomeCode.SUCCESS.value,
        sequence=sequence,
        result=raw,
        language=raw.language,
        duration_ms=_elapsed_ms(started),
    )


def fetch_transcript(
    video_id: str, *, providers: tuple[TranscriptProvider, ...] | None = None
) -> TranscriptOutcome:
    """provider 체인을 순서대로 시도해 성공까지의 모든 시도를 담아 반환한다.

    `providers`를 주지 않으면 `TRANSCRIPT_PROVIDER_ORDER` 설정으로 체인을 구성한다.
    성공 시 첫 성공 provider의 `TranscriptResult`를 wrap하고 이전 실패 시도까지 보존한다.
    """
    chain = providers if providers is not None else _resolve_provider_chain()
    attempts: list[TranscriptAttempt] = []
    for sequence, provider in enumerate(chain, start=1):
        attempt = _run_provider(provider, video_id, sequence)
        attempts.append(attempt)
        if attempt.succeeded:
            return TranscriptOutcome(result=attempt.result, attempts=attempts)
    return TranscriptOutcome(result=None, attempts=attempts)


async def fetch_transcript_async(
    video_id: str, *, providers: tuple[TranscriptProvider, ...] | None = None
) -> TranscriptOutcome:
    """블로킹 체인을 executor로 격리해 실행하고 관측 결과를 반환한다."""
    return await asyncio.to_thread(fetch_transcript, video_id, providers=providers)


async def fetch_captions_async(video_id: str) -> TranscriptOutcome:
    """캡션 전용 체인(whisper 제외)만 실행한다(T-172 병렬 fetch 진입점).

    순수 네트워크 I/O만 수행한다 — DB 세션에 접근하지 않으므로 다수 영상을
    `asyncio.Semaphore`로 동시에 호출해도 안전하다(session race 없음).
    """
    return await asyncio.to_thread(fetch_transcript, video_id, providers=caption_provider_chain())


def whisper_failure_attempt(
    exc: BaseException, *, started: float | None = None
) -> TranscriptAttempt:
    """raise된 예외를 whisper 실패 `TranscriptAttempt`로 분류한다(T-172).

    구 순차 체인의 `_run_provider` 예외 분기(raise된 provider 예외를 삼켜
    `_classify_exception`으로 코드화)와 **동일한 매핑**을 whisper 단건 경로에 재현한다.
    병렬화 이전 whisper는 provider 체인 안에서 실행돼 예외가 이렇게 분류·흡수됐으나,
    T-172로 whisper가 체인 밖 단건 호출이 되면서 이 안전망이 필요하다. sequence는
    `merge_outcomes`가 재부여하므로 여기서는 채우지 않는다(기본 0).
    """
    return TranscriptAttempt(
        provider=TranscriptProviderName.WHISPER.value,
        outcome=_classify_exception(exc),
        detail=_exc_detail(exc),
        duration_ms=_elapsed_ms(started) if started is not None else None,
    )


async def transcribe_whisper_async(
    video_id: str,
    *,
    force: bool = False,
    model_size: str | None = None,
) -> TranscriptAttempt:
    """whisper 단건 시도(T-172). `transcribe_via_whisper`의 얇은 async 래퍼다.

    caption과 달리 CPU 집약이라 호출자는 반드시 동시성 1로만 실행해야 한다(gather
    금지). `force=False`(기본, auto 경로)면 `TRANSCRIPT_WHISPER_ENABLED` 게이트를
    그대로 따르고, `force=True`(수동 재전사)면 게이트를 우회한다.

    `transcribe_via_whisper`는 대개 내부에서 예외를 삼켜 분류된 attempt를 반환하지만,
    그 try/except 밖(예: tempdir 생성)에서 예외가 튀어나올 수 있다. 구 순차 체인의
    `_run_provider`가 그런 예외를 분류·흡수했던 것과 동일하게, 여기서도 예외를 whisper
    실패 attempt로 변환하고 **절대 re-raise 하지 않는다** — 그래야 병렬화 후에도 whisper
    예외 하나가 poi_batch 전체를 죽이지 않고 description-fallback으로 이어진다.
    """
    started = time.monotonic()
    try:
        return await asyncio.to_thread(
            transcribe_via_whisper, video_id, force=force, model_size=model_size
        )
    except Exception as exc:
        return whisper_failure_attempt(exc, started=started)


def merge_outcomes(
    caption: TranscriptOutcome, whisper_attempt: TranscriptAttempt | None
) -> TranscriptOutcome:
    """캡션 outcome과 whisper 단건 시도를 순차 체인과 동일한 형태로 병합한다(T-172).

    `whisper_attempt`가 없으면 `caption`을 그대로 반환한다. 있으면 caption.attempts
    뒤에 sequence를 재부여해 이어붙이고(순차 체인이 whisper를 마지막 provider로
    시도했을 때와 동일한 attempts 형태), whisper가 성공하면 `result`를 whisper로
    승격한다(캡션이 이미 최종 실패했을 때만 호출되므로 caption.result는 항상 None).
    이렇게 해야 `TranscriptOutcome.success_provider`/`failure_code` 파생과
    `transcript_attempts` 기록 형태가 병렬 이전 순차 체인과 동일하게 유지된다.
    """
    if whisper_attempt is None:
        return caption
    from dataclasses import replace

    merged_attempt = replace(whisper_attempt, sequence=len(caption.attempts) + 1)
    attempts = [*caption.attempts, merged_attempt]
    result = merged_attempt.result if merged_attempt.succeeded else caption.result
    return TranscriptOutcome(result=result, attempts=attempts)


def get_transcript(
    video_id: str, *, providers: tuple[TranscriptProvider, ...] | None = None
) -> TranscriptResult | None:
    """성공 결과만 필요한 호출자용 얇은 래퍼(관측 없이 result만)."""
    return fetch_transcript(video_id, providers=providers).result


async def get_transcript_async(
    video_id: str, *, providers: tuple[TranscriptProvider, ...] | None = None
) -> TranscriptResult | None:
    """`get_transcript`의 async 래퍼(result만)."""
    return await asyncio.to_thread(get_transcript, video_id, providers=providers)

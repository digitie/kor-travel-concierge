// 수집 입력 자동 분류 — backend `ktc/etl/source_resolve.py`의 `classify_source_input`을
// 이식한 프런트 미리보기용 파서. 백엔드 판별과 우선순위·정규식을 같게 유지해
// "자동 인식" 힌트가 실제 수집 동작과 어긋나지 않게 한다.
// 우선순위: 재생목록(`list=`/`PL...`) → 영상(`watch?v=`/`youtu.be`/shorts) → 채널
// (`/channel/`·`/@handle`·`/c/`·`/user/`·legacy custom 경로·`@handle`·`UC...`) → 키워드(기본).
// 주의: Python urlparse와 WHATWG URL의 파서 차이(백슬래시·userinfo 등 변칙 입력)까지
// 완전히 같을 수는 없다. 이 판별은 참고용 힌트이며 최종 판별은 제출 시 backend가 수행한다.

export type SourceInputKind = "keyword" | "channel" | "playlist" | "video";

export type DetectedTarget = {
  kind: SourceInputKind;
  /** 추출된 표준 값(재생목록/영상은 ID, 채널·키워드는 원본) */
  value: string;
};

const CHANNEL_ID_RE = /^UC[0-9A-Za-z_-]{22}$/;
const PLAYLIST_ID_RE = /^(?:PL|UU|FL|OL|LL)[0-9A-Za-z_-]{10,}$/;
const VIDEO_ID_RE = /^[0-9A-Za-z_-]{11}$/;

function looksLikeUrl(raw: string): boolean {
  return (
    raw.startsWith("http://") ||
    raw.startsWith("https://") ||
    raw.includes("youtube.com") ||
    raw.includes("youtu.be")
  );
}

function withScheme(raw: string): string {
  return raw.startsWith("http://") || raw.startsWith("https://")
    ? raw
    : `https://${raw}`;
}

function parseUrl(raw: string): URL | null {
  try {
    return new URL(withScheme(raw));
  } catch {
    return null;
  }
}

function pathSegments(url: URL): string[] {
  return url.pathname
    .split("/")
    .filter(Boolean)
    .map((segment) => {
      try {
        return decodeURIComponent(segment);
      } catch {
        return segment;
      }
    });
}

/** 재생목록 입력에서 재생목록 ID(`PL...` 등)를 추출한다. 아니면 null */
export function parsePlaylistId(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;
  if (looksLikeUrl(value) || value.includes("list=")) {
    // URL 파싱 실패는 backend `_safe_urlparse` 폴백과 동일하게 '재생목록 아님'.
    const url = parseUrl(value);
    return url?.searchParams.get("list") || null;
  }
  return PLAYLIST_ID_RE.test(value) ? value : null;
}

/** 영상 URL에서 영상 ID(11자)를 추출한다. bare 문자열은 키워드와 모호해 null */
export function parseVideoId(raw: string): string | null {
  const value = raw.trim();
  if (!value || !looksLikeUrl(value)) return null;
  const url = parseUrl(value);
  if (!url) return null;
  const segments = pathSegments(url);
  if (url.hostname.toLowerCase().includes("youtu.be")) {
    return segments[0] && VIDEO_ID_RE.test(segments[0]) ? segments[0] : null;
  }
  const v = url.searchParams.get("v");
  if (v && VIDEO_ID_RE.test(v)) return v;
  if (
    segments.length >= 2 &&
    ["shorts", "embed", "v", "live"].includes(segments[0]) &&
    VIDEO_ID_RE.test(segments[1])
  ) {
    return segments[1];
  }
  return null;
}

/** 문자열이 YouTube 영상 ID(11자) 형식인지 */
export function isVideoId(value: string): boolean {
  return VIDEO_ID_RE.test(value.trim());
}

// backend `parse_channel_input`은 재생목록/영상이 아닌 URL 중 경로가 비어있지 않으면
// 전부 채널(id/handle/username/legacy custom)로 본다(`youtube.com/SomeName/videos` 포함).
// 경로가 빈 URL만 검색어(search)로 떨어진다.
function isChannelUrl(url: URL): boolean {
  return pathSegments(url).length > 0;
}

/** 수집 입력 문자열을 자동 분류한다(backend와 동일 우선순위). 빈 입력은 null */
export function detectSourceInput(raw: string): DetectedTarget | null {
  const value = raw.trim();
  if (!value) return null;
  const playlist = parsePlaylistId(value);
  if (playlist) return { kind: "playlist", value: playlist };
  const video = parseVideoId(value);
  if (video) return { kind: "video", value: video };
  if (looksLikeUrl(value)) {
    const url = parseUrl(value);
    if (url && isChannelUrl(url)) return { kind: "channel", value };
    return { kind: "keyword", value };
  }
  if (value.startsWith("@") || CHANNEL_ID_RE.test(value)) {
    return { kind: "channel", value };
  }
  return { kind: "keyword", value };
}

/** 선택한 대상 유형에 입력이 형식상 맞는지 검사한다(수집 폼 validation). */
export function validateTargetValue(
  targetType: "auto" | SourceInputKind,
  raw: string,
): string | null {
  const value = raw.trim();
  if (!value) return "수집 대상을 입력하세요.";
  if (targetType === "video") {
    if (parseVideoId(value) || isVideoId(value)) return null;
    return "영상 URL 또는 11자 영상 ID가 아닙니다.";
  }
  if (targetType === "playlist") {
    if (parsePlaylistId(value)) return null;
    return "재생목록 URL(list=...) 또는 PL... ID가 아닙니다.";
  }
  // channel/keyword/auto는 자유 입력(채널명·검색어)을 허용한다.
  return null;
}

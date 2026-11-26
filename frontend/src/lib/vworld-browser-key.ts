// 브라우저 지도용 VWorld 키는 build가 아니라 UI 서버 **실행 시** env에서 읽는다(T-212).
// `NEXT_PUBLIC_*`는 `next build`가 client·server 번들에 값을 박으므로 쓰지 않는다 — 키를 빠뜨린 build가
// 조용히 "키 없는" 이미지가 되던 문제(2026-11-18~25, T-211)와 키 교체 때마다 재빌드하던 문제를 함께 없앤다.
// 값은 인증된 관리자 화면의 서버 렌더 결과로만 브라우저에 간다((admin)/layout.tsx). 어디에도 값을 로그로 남기지 않는다.
export const VWORLD_BROWSER_KEY_ENV = "KTC_VWORLD_BROWSER_KEY";

// .env.example·문서의 자리표시자(`your_..._here`). 그대로 두면 키 없음으로 본다.
const PLACEHOLDER = /^your_[a-z0-9_]*_here$/i;
// 타일 URL 경로에 들어가는 값이라 URL 안전 문자만 받는다(VWorld 키는 영숫자와 '-'뿐이다).
const KEY_PATTERN = /^[A-Za-z0-9_-]+$/;

export type VWorldBrowserKeyStatus = "ok" | "missing" | "placeholder" | "malformed";
export type VWorldBrowserKey = { status: VWorldBrowserKeyStatus; key: string };

export function parseVWorldBrowserKey(raw: string | undefined): VWorldBrowserKey {
  // 앞뒤 공백·CR(.env CRLF)은 흔한 실수라 걷어 낸다. 그 밖에 형식이 다르면 키 없음으로 본다.
  const value = (raw ?? "").trim();
  if (!value) return { status: "missing", key: "" };
  if (PLACEHOLDER.test(value)) return { status: "placeholder", key: "" };
  if (!KEY_PATTERN.test(value)) return { status: "malformed", key: "" };
  return { status: "ok", key: value };
}

export function readVWorldBrowserKey(
  env: Readonly<Record<string, string | undefined>> = process.env,
): VWorldBrowserKey {
  return parseVWorldBrowserKey(env[VWORLD_BROWSER_KEY_ENV]);
}

// 서버 기동 경고 문구. 키 값은 싣지 않는다(이름과 상태만).
export function vworldBrowserKeyWarning(result: VWorldBrowserKey): string | null {
  const reason = {
    ok: null,
    // 옛 build 입력 이름에만 값을 둔 .env를 위한 안내. 옛 이름은 읽지 않는다.
    missing: "비어 있습니다(옛 이름 NEXT_PUBLIC_VWORLD_SERVICE_KEY는 더 이상 읽지 않습니다)",
    placeholder: ".env.example 자리표시자 그대로입니다",
    malformed: "형식이 올바르지 않습니다(영숫자·'-'·'_'만 허용, 따옴표 금지)",
  }[result.status];
  if (reason == null) return null;
  return `[ktc-ui] 경고: ${VWORLD_BROWSER_KEY_ENV}가 ${reason} — 지도는 "VWorld 지도 키 없음"으로 표시됩니다. UI 컨테이너 실행 env에 브라우저용 VWorld 키를 넣고 컨테이너를 다시 만드세요(재빌드 불필요).`;
}

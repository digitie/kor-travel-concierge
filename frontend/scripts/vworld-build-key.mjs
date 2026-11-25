// UI 이미지 build의 VWorld 키 판정(순수 함수). 실행 진입점은 require-vworld-build-key.mjs다 —
// Docker builder 단계에서 `npm run build` 직전에 돈다(frontend/Dockerfile).
//
// NEXT_PUBLIC_VWORLD_SERVICE_KEY는 `next build`가 브라우저 번들에 박는 값이라, build arg를 빠뜨리면
// 이미지가 조용히 "VWorld 지도 키 없음" 화면으로 빌드된다(2026-11-20~25 운영 UI 이미지 세 개가 그랬다 —
// Dockerfile ARG 기본값이 빈 문자열이라 빌드는 성공했다). 이 검사는 그 빈 값을 빌드 실패로 바꾼다.
//
// 키 없이 빌드해야 하는 경우(로컬 확인, 지도 없는 시험 이미지)는 build arg
// `KTC_ALLOW_KEYLESS_MAP_BUILD=1`을 명시한다 — 그때도 경고는 남긴다.
// 값은 공개 번들에 실리는 키지만 로그에는 싣지 않는다(길이·유무만 판정).
export const KEY_ENV = "NEXT_PUBLIC_VWORLD_SERVICE_KEY";
export const ALLOW_ENV = "KTC_ALLOW_KEYLESS_MAP_BUILD";
// README·.env.example의 자리표시자(`your_vworld_browser_key_here`) 꼴.
const PLACEHOLDER = /^your_.*_here$/i;

/**
 * @param {Record<string, string | undefined>} env
 * @returns {{ ok: boolean, level: "ok" | "warn" | "error", message: string }}
 */
export function checkVWorldBuildKey(env) {
  const allow = env[ALLOW_ENV] ?? "";
  if (allow !== "" && allow !== "1") {
    return {
      ok: false,
      level: "error",
      message: `${ALLOW_ENV}는 비우거나 1이어야 합니다(받은 값의 길이 ${allow.length}).`,
    };
  }
  const raw = env[KEY_ENV] ?? "";
  const key = raw.trim();
  if (key !== "") {
    // next build는 값을 손대지 않고 그대로 번들에 박는다(src/lib/api.ts) — 앞뒤 공백·CR·따옴표가 붙은 값이나
    // .env.example의 자리표시자도 '키 없음'과 같은 고장 난 지도를 만든다.
    if (raw !== key || /["'\s]/.test(key)) {
      return {
        ok: false,
        level: "error",
        message: `${KEY_ENV}에 공백·줄바꿈(CR)·따옴표가 섞여 있습니다(길이 ${raw.length}). 값만 넘기세요.`,
      };
    }
    if (PLACEHOLDER.test(key)) {
      return {
        ok: false,
        level: "error",
        message: `${KEY_ENV}가 .env.example의 자리표시자 그대로입니다. 실제 VWorld 브라우저 키를 넣으세요.`,
      };
    }
    return { ok: true, level: "ok", message: `${KEY_ENV} 확인(번들에 포함됨).` };
  }
  if (allow === "1") {
    return {
      ok: true,
      level: "warn",
      message:
        `경고: ${KEY_ENV} 없이 빌드합니다(${ALLOW_ENV}=1). ` +
        "이 이미지의 지도는 VWorld 타일 없이 '키 없음' 상태로 뜹니다 — 운영 prebuilt 배포에 쓰지 마세요.",
    };
  }
  return {
    ok: false,
    level: "error",
    message:
      `${KEY_ENV} build arg가 비어 있습니다. next build가 이 값을 브라우저 번들에 박으므로, 빠뜨리면 ` +
      "지도가 '키 없음'으로 뜨는 이미지가 조용히 만들어집니다. " +
      `\`--build-arg ${KEY_ENV}\`(값은 환경변수에서)로 넘기거나, 키 없는 이미지가 맞다면 ` +
      `\`--build-arg ${ALLOW_ENV}=1\`을 명시하세요.`,
  };
}

// 세션 없이 통과시키는 경로. proxy(인증)와 시험이 같은 정의를 쓴다.
// /maplibre/: 공개 라이브러리 worker 정적 파일(scripts/copy-maplibre-worker.mjs). 세션 만료 뒤
// worker 요청이 로그인 HTML로 redirect되면 지도 worker가 "Worker failed to load"로 죽는다.
const PUBLIC_PATH_PREFIXES = ["/api/auth/", "/_next/", "/favicon.ico", "/maplibre/"];

export function isPublicPath(pathname: string): boolean {
  return (
    pathname === "/login" ||
    PUBLIC_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix))
  );
}

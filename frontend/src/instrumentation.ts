// Next 서버 기동 때 한 번 실행된다. 브라우저 지도 키(KTC_VWORLD_BROWSER_KEY)가 없거나 이상하면 경고만 남긴다 —
// 지도는 "VWorld 지도 키 없음"으로 뜨고 나머지 화면은 정상이다. 키 값은 출력하지 않는다(T-212).
import { readVWorldBrowserKey, vworldBrowserKeyWarning } from "@/lib/vworld-browser-key";

export function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  // `next build`의 page data 수집 단계에서도 불린다. build에는 키가 필요 없으므로 그때는 경고하지 않는다.
  if (process.env.NEXT_PHASE === "phase-production-build") return;
  const warning = vworldBrowserKeyWarning(readVWorldBrowserKey());
  if (warning) console.warn(warning);
}

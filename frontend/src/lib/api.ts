// 백엔드 API 베이스 URL. `.env`의 NEXT_PUBLIC_API_BASE_URL로 주입한다.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// VWorld 지도 서비스 키 (브라우저 직접 로드).
export const VWORLD_SERVICE_KEY =
  process.env.NEXT_PUBLIC_VWORLD_SERVICE_KEY ?? "";

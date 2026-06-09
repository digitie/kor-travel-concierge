// REST API BFF 프록시 (ADR-24).
//
// 브라우저는 same-origin `/api/v1/*`로 요청하고, 이 Route Handler가 서버 사이드에서
// 백엔드로 프록시하며 인증 코드(`X-API-Key`)를 주입한다. 인증 키는 서버 전용 환경
// 변수(`BACKEND_API_KEY`, `NEXT_PUBLIC_` 아님)로만 보관해 브라우저 번들·네트워크에
// 노출되지 않는다. export(top-level navigation) 다운로드도 이 프록시를 거치므로
// 인증 환경에서 정상 동작한다.
import { type NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// 백엔드 origin(서버 사이드 전용). Compose에서는 컨테이너 간 `http://api:8000`.
const BACKEND_ORIGIN = (process.env.BACKEND_ORIGIN ?? "http://localhost:9041").replace(
  /\/$/,
  "",
);
// 서버 사이드 전용 인증 코드. 비어 있으면(로컬/E2E 무인증) 헤더를 붙이지 않는다.
const BACKEND_API_KEY = process.env.BACKEND_API_KEY ?? "";

// 프록시가 그대로 전달하면 안 되는 hop-by-hop / 자동 설정 헤더.
const SKIP_HEADERS = new Set([
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "keep-alive",
  "upgrade",
  "accept-encoding",
]);

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  const suffix = path.map(encodeURIComponent).join("/");
  const target = `${BACKEND_ORIGIN}/api/v1/${suffix}${request.nextUrl.search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!SKIP_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });
  if (BACKEND_API_KEY) {
    headers.set("X-API-Key", BACKEND_API_KEY);
  }

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    redirect: "manual",
  });

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!SKIP_HEADERS.has(key.toLowerCase())) {
      responseHeaders.set(key, value);
    }
  });

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

type RouteContext = { params: Promise<{ path: string[] }> };

async function handle(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  return proxy(request, path ?? []);
}

export {
  handle as GET,
  handle as POST,
  handle as PUT,
  handle as PATCH,
  handle as DELETE,
};

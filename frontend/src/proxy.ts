import { NextRequest, NextResponse } from "next/server";

import { requestSessionStatus, sanitizeLocalPath } from "@/lib/auth";
import { isPublicPath } from "@/lib/public-paths";

export async function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  const session = await requestSessionStatus(request);
  if (session === "unavailable") {
    return NextResponse.json({ error: "AUTH_UNAVAILABLE" }, { status: 503, headers: { "Retry-After": "1" } });
  }
  if (session === "valid") {
    if (pathname === "/login") {
      const redirectPath = sanitizeLocalPath(request.nextUrl.searchParams.get("next"));
      return NextResponse.redirect(new URL(redirectPath, request.url));
    }
    return NextResponse.next();
  }

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "AUTH_REQUIRED" }, { status: 401 });
  }

  const nextPath = `${pathname}${request.nextUrl.search}`;
  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", nextPath);
  return NextResponse.redirect(loginUrl);
}

// 인증을 건너뛰는 것은 경로 prefix로만 정한다(public-paths.ts의 정적 prefix와 같은 집합). 예전 matcher는
// 확장자(.png·.js·.css·.map 등)로 끝나는 모든 경로를 뺐다 — `/place/x.png`·`/review/1.css`처럼 동적 segment에
// 확장자를 붙이면 proxy 없이 관리자 레이아웃이 렌더돼 실행 시 지도 키(T-212)까지 인증 없이 실렸다.
// public/에는 빌드가 복사하는 maplibre worker만 있다.
export const config = {
  matcher: ["/((?!_next/static/|_next/image|favicon\\.ico$|maplibre/).*)"],
};

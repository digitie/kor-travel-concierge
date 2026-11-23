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

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|.*\\.(?:ico|png|jpg|jpeg|svg|webp|gif|css|js|map)$).*)",
  ],
};

import { NextRequest, NextResponse } from "next/server";

import { requestHasValidSession, sanitizeLocalPath } from "@/lib/auth";

const PUBLIC_PATH_PREFIXES = ["/api/auth/", "/_next/", "/favicon.ico"];

export async function proxy(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  const validSession = await requestHasValidSession(request);
  if (validSession) {
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

function isPublicPath(pathname: string): boolean {
  return (
    pathname === "/login" ||
    PUBLIC_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix))
  );
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|.*\\.(?:ico|png|jpg|jpeg|svg|webp|gif|css|js|map)$).*)",
  ],
};

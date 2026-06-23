import { NextRequest, NextResponse } from "next/server";

import { recordAuthAuditEvent } from "@/lib/auth-audit";
import {
  SESSION_COOKIE_NAME,
  checkLoginRateLimit,
  clearLoginFailures,
  createSessionCookieValue,
  recordLoginFailure,
  requestHasSameOrigin,
  revokeSessionCookieValue,
  sanitizeLocalPath,
  sessionCookieOptions,
  verifyAdminLogin,
} from "@/lib/auth";

export async function POST(request: NextRequest) {
  if (!requestHasSameOrigin(request)) {
    await recordAuthAuditEvent(request, {
      eventType: "login",
      outcome: "denied",
      reason: "invalid_origin",
    });
    return NextResponse.json({ error: "INVALID_ORIGIN" }, { status: 403 });
  }

  let payload: { username?: unknown; password?: unknown; next?: unknown };
  try {
    payload = (await request.json()) as typeof payload;
  } catch {
    await recordAuthAuditEvent(request, {
      eventType: "login",
      outcome: "denied",
      reason: "invalid_json",
    });
    return NextResponse.json({ error: "INVALID_JSON" }, { status: 400 });
  }

  const username = typeof payload.username === "string" ? payload.username : "";
  const password = typeof payload.password === "string" ? payload.password : "";
  const nextPath = sanitizeLocalPath(typeof payload.next === "string" ? payload.next : null);
  const rateLimit = checkLoginRateLimit(request);
  if (!rateLimit.allowed) {
    await recordAuthAuditEvent(request, {
      attemptedUsername: username,
      eventType: "login",
      nextPath,
      outcome: "denied",
      reason: "rate_limited",
    });
    return NextResponse.json(
      { error: "RATE_LIMITED" },
      {
        status: 429,
        headers: { "Retry-After": String(rateLimit.retryAfterSeconds) },
      },
    );
  }

  const result = await verifyAdminLogin({ username, password });
  if (result === "misconfigured") {
    await recordAuthAuditEvent(request, {
      attemptedUsername: username,
      eventType: "login",
      nextPath,
      outcome: "failed",
      reason: "misconfigured",
    });
    return NextResponse.json({ error: "AUTH_MISCONFIGURED" }, { status: 503 });
  }
  if (result !== "ok") {
    recordLoginFailure(request);
    await recordAuthAuditEvent(request, {
      attemptedUsername: username,
      eventType: "login",
      nextPath,
      outcome: "denied",
      reason: "invalid_credentials",
    });
    return NextResponse.json({ error: "INVALID_CREDENTIALS" }, { status: 401 });
  }

  clearLoginFailures(request);
  await revokeSessionCookieValue(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  await recordAuthAuditEvent(request, {
    attemptedUsername: username,
    eventType: "login",
    nextPath,
    outcome: "succeeded",
    reason: "authenticated",
  });

  const response = NextResponse.json({ ok: true, next: nextPath });
  response.cookies.set(
    SESSION_COOKIE_NAME,
    await createSessionCookieValue(request),
    sessionCookieOptions(request),
  );
  return response;
}

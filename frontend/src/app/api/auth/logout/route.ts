import { NextRequest, NextResponse } from "next/server";

import { recordAuthAuditEvent } from "@/lib/auth-audit";
import {
  SESSION_COOKIE_NAME,
  adminUsernameFromEnv,
  expiredSessionCookieOptions,
  requestHasSameOrigin,
  revokeSessionCookieValue,
} from "@/lib/auth";

export async function POST(request: NextRequest) {
  if (!requestHasSameOrigin(request)) {
    await recordAuthAuditEvent(request, {
      attemptedUsername: adminUsernameFromEnv(),
      eventType: "logout",
      outcome: "denied",
      reason: "invalid_origin",
    });
    return NextResponse.json({ error: "INVALID_ORIGIN" }, { status: 403 });
  }

  await revokeSessionCookieValue(request.cookies.get(SESSION_COOKIE_NAME)?.value);
  await recordAuthAuditEvent(request, {
    attemptedUsername: adminUsernameFromEnv(),
    eventType: "logout",
    outcome: "succeeded",
    reason: "user_logout",
  });
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE_NAME, "", expiredSessionCookieOptions(request));
  return response;
}

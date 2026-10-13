import type { NextRequest } from "next/server";

import { clientIpForSecurity } from "@/lib/auth";

const INTERNAL_BASE = (process.env.BACKEND_ORIGIN ?? "http://localhost:12601").replace(
  /\/$/,
  "",
);
const ADMIN_PROXY_SECRET_ENV = "KTC_ADMIN_PROXY_SECRET";
const AUTH_AUDIT_ACTOR = "ui-auth";
// 감사 저장소 장애가 인증 UI의 10초 응답 예산을 소진하지 않도록 제한한다.
const AUTH_AUDIT_TIMEOUT_MS = 2_000;

type AuthAuditEvent = {
  attemptedUsername?: string | null;
  eventType: "login" | "logout";
  nextPath?: string | null;
  outcome: "succeeded" | "failed" | "denied";
  reason?: string | null;
};

export async function recordAuthAuditEvent(
  request: NextRequest,
  event: AuthAuditEvent,
): Promise<void> {
  const headers = new Headers({
    "content-type": "application/json",
    "x-ktc-actor": AUTH_AUDIT_ACTOR,
  });
  const proxySecret = process.env[ADMIN_PROXY_SECRET_ENV]?.trim();
  if (proxySecret) {
    headers.set("x-ktc-admin-proxy-secret", proxySecret);
  }
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  // signal을 처리하지 않는 fetch/본문 취소 구현에도 호출자의 대기 상한을 보장한다.
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new DOMException("Auth audit timeout", "TimeoutError"));
    }, AUTH_AUDIT_TIMEOUT_MS);
  });
  try {
    await Promise.race([
      fetch(`${INTERNAL_BASE}/api/v1/admin/auth-events`, {
        method: "POST",
        signal: controller.signal,
        headers,
        body: JSON.stringify({
          attempted_username: event.attemptedUsername?.trim() || null,
          client_ip: clientIpForSecurity(request),
          event_type: event.eventType,
          next_path: event.nextPath ?? null,
          outcome: event.outcome,
          reason: event.reason ?? null,
          user_agent: request.headers.get("user-agent"),
        }),
      }).then((response) => {
        // 감사 결과 본문은 쓰지 않는다. 응답 스트림을 닫아 연결·버퍼를 남기지 않는다.
        return response.body?.cancel();
      }),
      deadline,
    ]);
  } catch {
    // 로그인/로그아웃 UX는 감사 로그 저장소 가용성에 종속시키지 않는다.
  } finally {
    clearTimeout(timer);
  }
}

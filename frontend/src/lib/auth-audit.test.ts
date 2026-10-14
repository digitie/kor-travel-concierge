import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const auth = vi.hoisted(() => ({
  adminUsernameFromEnv: vi.fn(() => "unit-user"),
  expiredSessionCookieOptions: vi.fn(() => ({ httpOnly: true, path: "/", maxAge: 0, expires: new Date(0) })),
  clientIpForSecurity: vi.fn(() => "127.0.0.1"),
  requestHasSameOrigin: vi.fn(() => true),
  checkLoginRateLimit: vi.fn(() => ({ allowed: true } as { allowed: boolean; retryAfterSeconds?: number })),
  verifyAdminLogin: vi.fn(async () => "ok"),
  clearLoginFailures: vi.fn(),
  recordLoginFailure: vi.fn(),
  createSessionCookieValue: vi.fn(async () => "unit-session"),
  revokeSessionCookieValue: vi.fn(async () => undefined),
  sanitizeLocalPath: vi.fn(() => "/dagster"),
  sessionCookieOptions: vi.fn(() => ({ httpOnly: true, path: "/", maxAge: 28800 })),
}));
vi.mock("@/lib/auth", () => ({ ...auth, SESSION_COOKIE_NAME: "ktc_ui_session" }));
import { recordAuthAuditEvent } from "./auth-audit";
import { POST as login } from "@/app/api/auth/login/route";
import { POST as logout } from "@/app/api/auth/logout/route";

function request() {
  return new NextRequest("http://localhost/api/auth/login", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "unit-user", password: "unit-password", next: "/dagster" }),
  });
}
describe("감사 HTTP 가용성과 인증 응답의 분리", () => {
  beforeEach(() => {
    vi.clearAllMocks(); vi.useFakeTimers();
    auth.requestHasSameOrigin.mockReturnValue(true);
    auth.checkLoginRateLimit.mockReturnValue({ allowed: true });
    auth.verifyAdminLogin.mockResolvedValue("ok");
    auth.createSessionCookieValue.mockResolvedValue("unit-session");
    auth.revokeSessionCookieValue.mockResolvedValue(undefined);
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it.each(["valid", "invalid", "logout", "origin", "rate-limit", "misconfigured"])(
    "감사 응답이 멈춰도 %s 결과와 쿠키 의미를 보존한다", async (mode) => {
      let signal: AbortSignal | undefined;
      vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
        signal = init.signal ?? undefined;
        signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
      })));
      if (mode === "invalid") auth.verifyAdminLogin.mockResolvedValue("invalid");
      if (mode === "misconfigured") auth.verifyAdminLogin.mockResolvedValue("misconfigured");
      if (mode === "origin") auth.requestHasSameOrigin.mockReturnValue(false);
      if (mode === "rate-limit") auth.checkLoginRateLimit.mockReturnValue({ allowed: false, retryAfterSeconds: 60 });
      let settled = false;
      const pending = (mode === "logout" ? logout(request()) : login(request())).then(response => { settled = true; return response; });
      await vi.advanceTimersByTimeAsync(1999); expect(settled).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      const response = await pending;
      expect(signal?.aborted).toBe(true);
      const statuses: Record<string, number> = { valid: 200, invalid: 401, logout: 200, origin: 403, "rate-limit": 429, misconfigured: 503 };
      expect(response.status).toBe(statuses[mode]);
      const cookie = response.headers.get("set-cookie");
      if (mode === "valid") { expect(cookie).toContain("ktc_ui_session=unit-session"); expect(auth.createSessionCookieValue).toHaveBeenCalledOnce(); }
      else if (mode === "logout") { expect(cookie).toContain("Max-Age=0"); expect(auth.revokeSessionCookieValue).toHaveBeenCalledOnce(); }
      else { expect(cookie).toBeNull(); expect(auth.createSessionCookieValue).not.toHaveBeenCalled(); }
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it.each(["create", "replace", "logout"])("세션 상태 실패 %s는 성공 쿠키나 성공 감사로 바꾸지 않는다", async (mode) => {
    const fetch = vi.fn().mockResolvedValue(new Response("audit accepted")); vi.stubGlobal("fetch", fetch);
    if (mode === "create") auth.createSessionCookieValue.mockRejectedValue(new Error("unit storage unavailable"));
    else auth.revokeSessionCookieValue.mockRejectedValue(new Error("unit storage unavailable"));
    const response = await (mode === "logout" ? logout(request()) : login(request()));
    expect(response.status).toBe(503); expect(await response.json()).toEqual({ error: "AUTH_UNAVAILABLE" });
    expect(response.headers.get("set-cookie")).toBeNull();
    const event = JSON.parse(fetch.mock.calls[0][1].body);
    expect(event.outcome).toBe("failed"); expect(event.reason).toBe("session_state_unavailable");
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["fetch", "cancel"])("중단을 무시하는 %s도 호출자 대기를 끝낸다", async (mode) => {
    let signal: AbortSignal | undefined;
    const cancel = vi.fn(() => new Promise<void>(() => undefined));
    vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => {
      signal = init.signal ?? undefined;
      return mode === "fetch"
        ? new Promise<Response>(() => undefined)
        : Promise.resolve(new Response(new ReadableStream({ cancel })));
    }));
    let settled = false;
    const pending = recordAuthAuditEvent(request(), { eventType: "login", outcome: "succeeded" })
      .then(() => { settled = true; });
    await vi.advanceTimersByTimeAsync(1999); expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1); await pending;
    expect(signal?.aborted).toBe(true);
    expect(settled).toBe(true); expect(vi.getTimerCount()).toBe(0);
    if (mode === "cancel") expect(cancel).toHaveBeenCalledOnce();
  });

  it("즉시 실패한 감사 요청은 응답을 기다리지 않고 timer를 회수한다", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("unit connection refused")));
    await recordAuthAuditEvent(request(), { eventType: "login", outcome: "denied" });
    expect(vi.getTimerCount()).toBe(0);
  });

  it("정상 감사 응답 본문을 취소하고 timer를 회수한다", async () => {
    const response = new Response("unit audit response");
    const cancel = vi.spyOn(response.body!, "cancel");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await recordAuthAuditEvent(request(), { eventType: "login", outcome: "succeeded" });
    expect(cancel).toHaveBeenCalledOnce(); expect(vi.getTimerCount()).toBe(0);
  });
});

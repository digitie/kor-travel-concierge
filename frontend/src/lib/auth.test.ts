import { describe, expect, it } from "vitest";

import {
  checkLoginRateLimit,
  clearLoginFailures,
  createSessionCookieValue,
  hashAdminPasswordForEnv,
  recordLoginFailure,
  requestHasSameOrigin,
  sanitizeLocalPath,
  verifyAdminLogin,
  verifySessionCookieValue,
} from "@/lib/auth";

const STRONG_SECRET = "0123456789abcdef0123456789abcdef01234567"; // >= 32 chars
const baseEnv = { KTC_UI_SESSION_SECRET: STRONG_SECRET, KTC_ADMIN_USERNAME: "admin" };

// 헤더 없는 최소 RequestLike (forwarded IP 미신뢰 → loginAttemptKey ip='local').
const fakeRequest = { headers: { get: () => null } } as never;

describe("sanitizeLocalPath", () => {
  it("로컬 경로는 그대로 통과한다", () => {
    expect(sanitizeLocalPath("/destinations")).toBe("/destinations");
  });
  it("미지정/빈 값은 fallback", () => {
    expect(sanitizeLocalPath(null)).toBe("/");
    expect(sanitizeLocalPath("")).toBe("/");
  });
  it("open-redirect 패턴(//, 백슬래시, 비-/ 시작)을 거부한다", () => {
    expect(sanitizeLocalPath("//evil.com")).toBe("/");
    expect(sanitizeLocalPath("/\\evil.com")).toBe("/");
    expect(sanitizeLocalPath("https://evil.com")).toBe("/");
    expect(sanitizeLocalPath("%2F%2Fevil.com")).toBe("/");
  });
});

describe("verifyAdminLogin", () => {
  it("올바른 자격은 ok, 틀린 비밀번호는 invalid", async () => {
    const hash = await hashAdminPasswordForEnv("correct-horse");
    const env = { ...baseEnv, KTC_ADMIN_PASSWORD_HASH: hash };
    expect(await verifyAdminLogin({ username: "admin", password: "correct-horse" }, env)).toBe("ok");
    expect(await verifyAdminLogin({ username: "admin", password: "wrong" }, env)).toBe("invalid");
    expect(await verifyAdminLogin({ username: "intruder", password: "correct-horse" }, env)).toBe(
      "invalid",
    );
  });
  it("해시/세션시크릿 미설정 시 misconfigured", async () => {
    expect(await verifyAdminLogin({ username: "admin", password: "x" }, baseEnv)).toBe(
      "misconfigured",
    );
  });
});

describe("session cookie sign/verify", () => {
  it("정상 발급 토큰은 검증을 통과한다", async () => {
    const value = await createSessionCookieValue(null, baseEnv, 1_000_000);
    expect(await verifySessionCookieValue(value, baseEnv, 1_000_000, null)).toBe(true);
  });
  it("서명 변조 토큰은 거부한다", async () => {
    const value = await createSessionCookieValue(null, baseEnv, 1_000_000);
    const [payload] = value.split(".");
    const tampered = `${payload}.AAAAAAAAAAAAAAAAAAAAAA`;
    expect(await verifySessionCookieValue(tampered, baseEnv, 1_000_000, null)).toBe(false);
  });
  it("만료된 토큰은 거부한다", async () => {
    const value = await createSessionCookieValue(null, baseEnv, 1_000_000);
    const future = 1_000_000 + (8 * 60 * 60 + 60) * 1000 + 1000;
    expect(await verifySessionCookieValue(value, baseEnv, future, null)).toBe(false);
  });
  it("다른 관리자 계정으로 발급된 토큰은 거부한다", async () => {
    const value = await createSessionCookieValue(null, baseEnv, 1_000_000);
    const otherEnv = { ...baseEnv, KTC_ADMIN_USERNAME: "someone-else" };
    expect(await verifySessionCookieValue(value, otherEnv, 1_000_000, null)).toBe(false);
  });
});

describe("requestHasSameOrigin (CSRF origin check)", () => {
  // 프록시가 X-Forwarded-Proto를 안 보내 내부적으로 http로 보이는 요청을 모사.
  function req(origin: string | null, extra: Record<string, string> = {}) {
    const all: Record<string, string | null> = { origin, ...extra };
    return {
      headers: { get: (n: string) => all[n.toLowerCase()] ?? null },
      nextUrl: { host: "internal:12605", protocol: "http:" },
    } as never;
  }
  const env = { KTC_UI_PUBLIC_ORIGINS: "https://concierge.example.org, https://www.concierge.example.org" };

  it("Origin 헤더가 없으면 통과", () => {
    expect(requestHasSameOrigin(req(null), env)).toBe(true);
  });
  it("재구성된 same-origin이면 통과(화이트리스트 불필요)", () => {
    expect(requestHasSameOrigin(req("http://internal:12605"), env)).toBe(true);
  });
  it("프록시가 proto를 빼먹어도, 신뢰 공개 origin이면 통과", () => {
    // requestOrigin은 http://internal:12605로 재구성되어 불일치하지만 화이트리스트가 허용.
    expect(requestHasSameOrigin(req("https://concierge.example.org"), env)).toBe(true);
  });
  it("화이트리스트에 없는 외부 origin은 거부(CSRF 방어 유지)", () => {
    expect(requestHasSameOrigin(req("https://evil.example"), env)).toBe(false);
  });
  it("화이트리스트 미설정이면 헤더 기반 검사만(불일치 origin 거부)", () => {
    expect(requestHasSameOrigin(req("https://concierge.example.org"), {})).toBe(false);
  });
});

describe("login rate limit", () => {
  it("계정별 버킷으로 임계 초과 시 차단하고 다른 계정은 영향이 없다", () => {
    clearLoginFailures(fakeRequest, "victim");
    clearLoginFailures(fakeRequest, "bystander");
    for (let i = 0; i < 5; i += 1) {
      recordLoginFailure(fakeRequest, undefined, "victim");
    }
    expect(checkLoginRateLimit(fakeRequest, undefined, "victim").allowed).toBe(false);
    expect(checkLoginRateLimit(fakeRequest, undefined, "bystander").allowed).toBe(true);
    clearLoginFailures(fakeRequest, "victim");
    expect(checkLoginRateLimit(fakeRequest, undefined, "victim").allowed).toBe(true);
  });
});

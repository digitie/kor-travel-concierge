import type { NextRequest } from "next/server";

export const SESSION_COOKIE_NAME = "ktc_ui_session";
export const SESSION_TTL_SECONDS = 8 * 60 * 60;

const ADMIN_USERNAME_ENV = "KTC_ADMIN_USERNAME";
const ADMIN_PASSWORD_HASH_ENV = "KTC_ADMIN_PASSWORD_HASH";
const SESSION_SECRET_ENV = "KTC_UI_SESSION_SECRET";
const PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256";
const PASSWORD_HASH_ITERATIONS = 310_000;
const SESSION_ALGORITHM = "HMAC";
const SESSION_AUDIENCE = "kor-travel-concierge-ui";
const SESSION_VERSION = 1;
const SESSION_ID_BYTES = 32;
const SESSION_SECRET_MIN_LENGTH = 32;
const SESSION_CLOCK_SKEW_SECONDS = 60;
const LOGIN_FAILURE_LIMIT = 5;
const LOGIN_FAILURE_WINDOW_SECONDS = 10 * 60;
const MAX_COOKIE_VALUE_LENGTH = 2048;
const BASE64URL_RE = /^[0-9A-Za-z_-]+$/;
const TRUST_FORWARDED_IPS_ENV = "KTC_UI_TRUST_FORWARDED_IPS";

type Env = Record<string, string | undefined>;
type HeaderReader = { get(name: string): string | null };
type RequestLike = { headers: HeaderReader; nextUrl?: { host: string; protocol: string } };

export type LoginVerification = "ok" | "invalid" | "misconfigured";
export type LoginRateLimitResult =
  | { allowed: true }
  | { allowed: false; retryAfterSeconds: number };

type SessionPayload = {
  aud: string;
  exp: number;
  fp: string;
  iat: number;
  sid: string;
  sub: string;
  v: number;
};

type LoginFailureBucket = {
  count: number;
  resetAt: number;
};

const revokedSessionIds = new Map<string, number>();
const loginFailures = new Map<string, LoginFailureBucket>();

export function adminUsernameFromEnv(env: Env = process.env): string {
  return (env[ADMIN_USERNAME_ENV] ?? "admin").trim() || "admin";
}

export async function verifyAdminLogin(
  input: { username: string; password: string },
  env: Env = process.env,
): Promise<LoginVerification> {
  const expectedUsername = adminUsernameFromEnv(env);
  const passwordHash = env[ADMIN_PASSWORD_HASH_ENV]?.trim();
  const sessionSecret = env[SESSION_SECRET_ENV]?.trim();
  if (!passwordHash || !sessionSecretIsStrong(sessionSecret)) {
    return "misconfigured";
  }
  // 사용자명이 불일치하더라도 PBKDF2 검증을 항상 수행한다. 불일치 시 즉시 반환하면
  // 응답 시간이 사용자명 일치 여부에 의존해 username 열거 타이밍 사이드채널이 된다.
  const usernameOk = constantTimeEqual(input.username.trim(), expectedUsername);
  const passwordOk = await verifyPassword(input.password, passwordHash);
  return usernameOk && passwordOk ? "ok" : "invalid";
}

export async function hashAdminPasswordForEnv(
  password: string,
  salt: Uint8Array = randomBytes(16),
  iterations = PASSWORD_HASH_ITERATIONS,
): Promise<string> {
  const hash = await pbkdf2(password, salt, iterations);
  return [
    PASSWORD_HASH_ALGORITHM,
    String(iterations),
    base64UrlEncode(salt),
    base64UrlEncode(hash),
  ].join("$");
}

export async function createSessionCookieValue(
  source: HeaderReader | RequestLike | null = null,
  env: Env = process.env,
  nowMs = Date.now(),
): Promise<string> {
  const secret = env[SESSION_SECRET_ENV]?.trim();
  if (!sessionSecretIsStrong(secret)) {
    throw new Error("KTC_UI_SESSION_SECRET is not configured or is too short");
  }
  const issuedAt = Math.floor(nowMs / 1000);
  const payload: SessionPayload = {
    aud: SESSION_AUDIENCE,
    exp: issuedAt + SESSION_TTL_SECONDS,
    fp: await sessionFingerprint(source, secret),
    iat: issuedAt,
    sid: base64UrlEncode(randomBytes(SESSION_ID_BYTES)),
    sub: adminUsernameFromEnv(env),
    v: SESSION_VERSION,
  };
  const payloadPart = base64UrlEncode(new TextEncoder().encode(JSON.stringify(payload)));
  const signature = await signSession(payloadPart, secret);
  return `${payloadPart}.${signature}`;
}

export async function verifySessionCookieValue(
  value: string | undefined,
  env: Env = process.env,
  nowMs = Date.now(),
  source: HeaderReader | RequestLike | null = null,
): Promise<boolean> {
  const secret = env[SESSION_SECRET_ENV]?.trim();
  if (!value || !sessionSecretIsStrong(secret)) {
    return false;
  }
  const payload = await decodeSignedSession(value, secret);
  if (payload === null) {
    return false;
  }
  return validateSessionPayload(payload, {
    env,
    nowSeconds: Math.floor(nowMs / 1000),
    secret,
    source,
  });
}

export async function revokeSessionCookieValue(
  value: string | undefined,
  env: Env = process.env,
  nowMs = Date.now(),
): Promise<void> {
  const secret = env[SESSION_SECRET_ENV]?.trim();
  if (!value || !sessionSecretIsStrong(secret)) {
    return;
  }
  const payload = await decodeSignedSession(value, secret);
  const nowSeconds = Math.floor(nowMs / 1000);
  if (payload !== null && payload.exp > nowSeconds && isBase64UrlString(payload.sid)) {
    cleanupRevokedSessions(nowSeconds);
    revokedSessionIds.set(payload.sid, payload.exp);
  }
}

export async function requestHasValidSession(
  request: NextRequest,
  env: Env = process.env,
): Promise<boolean> {
  return verifySessionCookieValue(
    request.cookies.get(SESSION_COOKIE_NAME)?.value,
    env,
    Date.now(),
    request,
  );
}

export function sessionCookieOptions(request: RequestLike | null = null) {
  return {
    httpOnly: true,
    sameSite: "strict" as const,
    secure: isHttpsRequest(request),
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  };
}

export function expiredSessionCookieOptions(request: RequestLike | null = null) {
  return {
    ...sessionCookieOptions(request),
    maxAge: 0,
  };
}

export function requestHasSameOrigin(request: RequestLike): boolean {
  const origin = request.headers.get("origin");
  if (!origin) {
    return true;
  }
  try {
    return normalizeOrigin(origin) === requestOrigin(request);
  } catch {
    return false;
  }
}

export function checkLoginRateLimit(
  request: RequestLike,
  nowMs = Date.now(),
  identifier?: string,
): LoginRateLimitResult {
  const nowSeconds = Math.floor(nowMs / 1000);
  cleanupLoginFailures(nowSeconds);
  const bucket = loginFailures.get(loginAttemptKey(request, identifier));
  if (!bucket || bucket.resetAt <= nowSeconds || bucket.count < LOGIN_FAILURE_LIMIT) {
    return { allowed: true };
  }
  return { allowed: false, retryAfterSeconds: Math.max(bucket.resetAt - nowSeconds, 1) };
}

export function recordLoginFailure(
  request: RequestLike,
  nowMs = Date.now(),
  identifier?: string,
): void {
  const nowSeconds = Math.floor(nowMs / 1000);
  cleanupLoginFailures(nowSeconds);
  const key = loginAttemptKey(request, identifier);
  const current = loginFailures.get(key);
  if (!current || current.resetAt <= nowSeconds) {
    loginFailures.set(key, {
      count: 1,
      resetAt: nowSeconds + LOGIN_FAILURE_WINDOW_SECONDS,
    });
    return;
  }
  loginFailures.set(key, { ...current, count: current.count + 1 });
}

export function clearLoginFailures(request: RequestLike, identifier?: string): void {
  loginFailures.delete(loginAttemptKey(request, identifier));
}

export function sanitizeLocalPath(raw: string | null | undefined, fallback = "/"): string {
  if (!raw) {
    return fallback;
  }
  try {
    const decoded = decodeURIComponent(raw);
    if (!decoded.startsWith("/") || decoded.startsWith("//") || decoded.includes("\\")) {
      return fallback;
    }
    return decoded;
  } catch {
    return fallback;
  }
}

export function clientIpForSecurity(request: RequestLike, env: Env = process.env): string | null {
  if (!isEnabled(env[TRUST_FORWARDED_IPS_ENV])) {
    return null;
  }
  return (
    firstForwardedValue(request.headers.get("x-forwarded-for")) ??
    firstForwardedValue(request.headers.get("x-real-ip"))
  );
}

async function verifyPassword(password: string, encoded: string): Promise<boolean> {
  const parts = encoded.split("$");
  if (parts.length !== 4 || parts[0] !== PASSWORD_HASH_ALGORITHM) {
    return false;
  }
  const iterations = Number(parts[1]);
  if (!Number.isInteger(iterations) || iterations < 100_000) {
    return false;
  }
  const salt = base64UrlDecode(parts[2]);
  const expected = base64UrlDecode(parts[3]);
  const actual = await pbkdf2(password, salt, iterations);
  return constantTimeEqualBytes(actual, expected);
}

async function decodeSignedSession(
  value: string,
  secret: string,
): Promise<SessionPayload | null> {
  if (value.length > MAX_COOKIE_VALUE_LENGTH) {
    return null;
  }
  const [payloadPart, signaturePart, extra] = value.split(".");
  if (
    !payloadPart ||
    !signaturePart ||
    extra !== undefined ||
    !isBase64UrlString(payloadPart) ||
    !isBase64UrlString(signaturePart)
  ) {
    return null;
  }
  const expectedSignature = await signSession(payloadPart, secret);
  if (!constantTimeEqual(signaturePart, expectedSignature)) {
    return null;
  }
  try {
    const parsed = JSON.parse(
      new TextDecoder().decode(base64UrlDecode(payloadPart)),
    ) as Partial<SessionPayload>;
    return sessionPayloadHasShape(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

async function validateSessionPayload(
  payload: SessionPayload,
  context: {
    env: Env;
    nowSeconds: number;
    secret: string;
    source: HeaderReader | RequestLike | null;
  },
): Promise<boolean> {
  if (payload.v !== SESSION_VERSION || payload.aud !== SESSION_AUDIENCE) {
    return false;
  }
  if (payload.sub !== adminUsernameFromEnv(context.env)) {
    return false;
  }
  if (payload.iat > context.nowSeconds + SESSION_CLOCK_SKEW_SECONDS) {
    return false;
  }
  if (payload.exp <= context.nowSeconds) {
    return false;
  }
  if (payload.exp - payload.iat > SESSION_TTL_SECONDS + SESSION_CLOCK_SKEW_SECONDS) {
    return false;
  }
  if (sessionIsRevoked(payload.sid, context.nowSeconds)) {
    return false;
  }
  const expectedFingerprint = await sessionFingerprint(context.source, context.secret);
  return constantTimeEqual(payload.fp, expectedFingerprint);
}

function sessionPayloadHasShape(payload: Partial<SessionPayload>): payload is SessionPayload {
  return (
    payload.aud === SESSION_AUDIENCE &&
    typeof payload.exp === "number" &&
    Number.isInteger(payload.exp) &&
    typeof payload.fp === "string" &&
    isBase64UrlString(payload.fp) &&
    typeof payload.iat === "number" &&
    Number.isInteger(payload.iat) &&
    typeof payload.sid === "string" &&
    isBase64UrlString(payload.sid) &&
    typeof payload.sub === "string" &&
    payload.v === SESSION_VERSION
  );
}

async function sessionFingerprint(
  source: HeaderReader | RequestLike | null,
  secret: string,
): Promise<string> {
  const userAgent = (headersFrom(source)?.get("user-agent") ?? "").slice(0, 300);
  return signSession(`fingerprint:${userAgent}`, secret);
}

async function pbkdf2(password: string, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: salt as BufferSource, iterations },
    key,
    256,
  );
  return new Uint8Array(bits);
}

async function signSession(payloadPart: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: SESSION_ALGORITHM, hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    SESSION_ALGORITHM,
    key,
    new TextEncoder().encode(payloadPart),
  );
  return base64UrlEncode(new Uint8Array(signature));
}

function randomBytes(length: number): Uint8Array {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return bytes;
}

function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function base64UrlDecode(value: string): Uint8Array {
  if (!isBase64UrlString(value) || value.length % 4 === 1) {
    throw new Error("invalid base64url");
  }
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function isBase64UrlString(value: string): boolean {
  return value.length > 0 && BASE64URL_RE.test(value);
}

function constantTimeEqual(left: string, right: string): boolean {
  return constantTimeEqualBytes(new TextEncoder().encode(left), new TextEncoder().encode(right));
}

function constantTimeEqualBytes(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) {
    return false;
  }
  let diff = 0;
  for (let i = 0; i < left.length; i += 1) {
    diff |= left[i] ^ right[i];
  }
  return diff === 0;
}

function sessionSecretIsStrong(value: string | undefined): value is string {
  return typeof value === "string" && value.length >= SESSION_SECRET_MIN_LENGTH;
}

function headersFrom(source: HeaderReader | RequestLike | null): HeaderReader | null {
  if (!source) {
    return null;
  }
  return "headers" in source ? source.headers : source;
}

function firstForwardedValue(value: string | null): string | null {
  return value?.split(",")[0]?.trim() || null;
}

function requestOrigin(request: RequestLike): string {
  const proto =
    firstForwardedValue(request.headers.get("x-forwarded-proto")) ??
    request.nextUrl?.protocol.replace(":", "") ??
    "http";
  const host =
    firstForwardedValue(request.headers.get("x-forwarded-host")) ??
    firstForwardedValue(request.headers.get("host")) ??
    request.nextUrl?.host;
  if (!host) {
    return "";
  }
  return normalizeOrigin(`${proto}://${host}`);
}

function normalizeOrigin(value: string): string {
  const url = new URL(value);
  return `${url.protocol}//${url.host}`.toLowerCase();
}

function isHttpsRequest(request: RequestLike | null): boolean {
  const forwardedProto = firstForwardedValue(request?.headers.get("x-forwarded-proto") ?? null);
  if (forwardedProto) {
    return forwardedProto.toLowerCase() === "https";
  }
  if (request?.nextUrl?.protocol) {
    return request.nextUrl.protocol === "https:";
  }
  return process.env.NODE_ENV === "production";
}

function loginAttemptKey(request: RequestLike, identifier?: string): string {
  // 신뢰 가능한 client IP가 있으면 IP+계정으로 버킷을 나눠 정확한 per-client 제한을
  // 적용한다. 신뢰 IP가 없으면(KTC_UI_TRUST_FORWARDED_IPS=off) IP가 'local'로 떨어지므로
  // 모든 시도가 계정 단위로만 묶인다. 효과적인 per-client 제한을 위해서는 운영에서
  // (리버스 프록시 IP 고정을 전제로) KTC_UI_TRUST_FORWARDED_IPS 활성화를 권장한다.
  const ip = (clientIpForSecurity(request) ?? "local").slice(0, 128);
  const who = (identifier ?? "").trim().toLowerCase().slice(0, 64);
  return `${ip}|${who}`;
}

function cleanupLoginFailures(nowSeconds: number): void {
  for (const [key, bucket] of loginFailures) {
    if (bucket.resetAt <= nowSeconds) {
      loginFailures.delete(key);
    }
  }
}

function sessionIsRevoked(sessionId: string, nowSeconds: number): boolean {
  cleanupRevokedSessions(nowSeconds);
  return revokedSessionIds.has(sessionId);
}

function cleanupRevokedSessions(nowSeconds: number): void {
  for (const [sessionId, expiresAt] of revokedSessionIds) {
    if (expiresAt <= nowSeconds) {
      revokedSessionIds.delete(sessionId);
    }
  }
}

function isEnabled(value: string | undefined): boolean {
  return value === "1" || value?.toLowerCase() === "true";
}

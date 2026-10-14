import { chmod, mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

let directory: string;
let env: Record<string, string>;
beforeEach(async () => {
  directory = await mkdtemp(join(tmpdir(), "concierge-session-test-"));
  env = { KTC_UI_SESSION_SECRET: "test-only-0123456789abcdef0123456789abcdef", KTC_ADMIN_USERNAME: "admin", KTC_UI_SESSION_STATE_DIR: directory };
});
afterEach(async () => { await rm(directory, { recursive: true, force: true }); vi.resetModules(); vi.doUnmock("node:fs/promises"); vi.useRealTimers(); });

it("서로 독립된 인증 번들에서 로그아웃한 쿠키를 거절한다", async () => {
  const first = await import("./auth");
  const cookie = await first.createSessionCookieValue(null, env);
  const otherCookie = await first.createSessionCookieValue(null, env);
  vi.resetModules();
  const second = await import("./auth");
  expect(await second.verifySessionCookieValue(cookie, env)).toBe(true);
  await first.revokeSessionCookieValue(cookie, env);
  expect(await second.verifySessionCookieValue(cookie, env)).toBe(false);
  expect(await second.verifySessionCookieValue(otherCookie, env)).toBe(true);
});

it("동시에 nonce를 초기화한 모든 번들이 같은 서명을 검증한다", async () => {
  const auth = await import("./auth");
  const results = await Promise.allSettled(Array.from({ length: 32 }, () => auth.createSessionCookieValue(null, env)));
  const cookies = results.filter((result): result is PromiseFulfilledResult<string> => result.status === "fulfilled").map(result => result.value);
  expect(cookies).toHaveLength(8);
  expect(results.filter(result => result.status === "rejected")).toHaveLength(24);
  expect(await Promise.all(cookies.map(cookie => auth.verifySessionCookieValue(cookie, env)))).toEqual(Array(8).fill(true));
});

it("상태 디렉터리를 잃으면 기존 쿠키는 거절하고 새 로그인을 허용한다", async () => {
  const auth = await import("./auth"); const cookie = await auth.createSessionCookieValue(null, env);
  await rm(directory, { recursive: true });
  expect(await auth.verifySessionCookieValue(cookie, env)).toBe(false);
  const next = await auth.createSessionCookieValue(null, env);
  expect(await auth.verifySessionCookieValue(next, env)).toBe(true);
});

it("private 상태 오류는 서명만으로 통과하지 않는다", async () => {
  const auth = await import("./auth"); const cookie = await auth.createSessionCookieValue(null, env);
  await writeFile(join(directory, "nonce"), "invalid", { mode: 0o600 });
  expect(await auth.verifySessionCookieValue(cookie, env)).toBe(false);
  await expect(auth.createSessionCookieValue(null, env)).rejects.toThrow();
  await expect(auth.revokeSessionCookieValue(cookie, env)).rejects.toThrow();
});

it("symlink 또는 공개 디렉터리를 상태 저장소로 쓰지 않는다", async () => {
  const auth = await import("./auth"); const target = join(directory, "private"); await mkdir(target, { mode: 0o700 });
  const alias = join(directory, "alias"); await symlink(target, alias);
  await expect(auth.createSessionCookieValue(null, { ...env, KTC_UI_SESSION_STATE_DIR: alias })).rejects.toThrow();
  await chmod(target, 0o755);
  await expect(auth.createSessionCookieValue(null, { ...env, KTC_UI_SESSION_STATE_DIR: target })).rejects.toThrow();
});

it("만료 hour 버킷만 지우고 같은 상태의 유효 세션 폐기는 보존한다", async () => {
  const auth = await import("./auth"); const now = 100_000_000;
  const old = await auth.createSessionCookieValue(null, env, now);
  await auth.revokeSessionCookieValue(old, env, now);
  const currentTime = now + 9 * 3600_000;
  const next = await auth.createSessionCookieValue(null, env, currentTime);
  await auth.revokeSessionCookieValue(next, env, currentTime);
  expect(await auth.verifySessionCookieValue(next, env, currentTime)).toBe(false);
  const { readdir } = await import("node:fs/promises");
  const buckets = (await readdir(directory)).filter(name => name.startsWith("r-"));
  expect(buckets).toHaveLength(1);
});

it("상태 I/O가 영구 대기해도 2초 뒤 인증 거절·발급/폐기 실패로 끝낸다", async () => {
  const original = await import("./auth"); const cookie = await original.createSessionCookieValue(null, env);
  vi.resetModules();
  vi.doMock("node:fs/promises", async () => ({
    ...await vi.importActual("node:fs/promises"), mkdir: () => new Promise(() => undefined),
  }));
  const auth = await import("./auth"); vi.useFakeTimers();
  const verify = auth.verifySessionCookieValue(cookie, env);
  const create = auth.createSessionCookieValue(null, env).then(() => "unexpected", () => "rejected");
  const revoke = auth.revokeSessionCookieValue(cookie, env).then(() => "unexpected", () => "rejected");
  await vi.advanceTimersByTimeAsync(2000);
  expect(await verify).toBe(false); expect(await create).toBe("rejected"); expect(await revoke).toBe("rejected");
  expect(vi.getTimerCount()).toBe(0);
});

it("timeout 뒤에도 실제 I/O가 끝나기 전 슬롯을 유지하고 회복 뒤 다시 입장한다", async () => {
  const original = await import("./auth"); const cookie = await original.createSessionCookieValue(null, env);
  vi.resetModules();
  const actual = await vi.importActual<typeof import("node:fs/promises")>("node:fs/promises");
  const pending: Array<() => void> = [];
  const blocked = vi.fn(() => new Promise<void>(resolve => { pending.push(resolve); }));
  vi.doMock("node:fs/promises", () => ({ ...actual, mkdir: blocked }));
  const auth = await import("./auth"); vi.useFakeTimers();
  const first = Promise.all(Array.from({ length: 100 }, () => auth.verifySessionCookieValue(cookie, env)));
  await vi.advanceTimersByTimeAsync(2000); expect(await first).toEqual(Array(100).fill(false));
  expect(blocked).toHaveBeenCalledTimes(8); expect(pending).toHaveLength(8);
  const second = await Promise.all(Array.from({ length: 100 }, () => auth.verifySessionCookieValue(cookie, env)));
  expect(second).toEqual(Array(100).fill(false)); expect(blocked).toHaveBeenCalledTimes(8); expect(vi.getTimerCount()).toBe(0);
  await expect(auth.createSessionCookieValue(null, env)).rejects.toThrow("busy");
  await expect(auth.revokeSessionCookieValue(cookie, env)).rejects.toThrow("busy");
  vi.useRealTimers();
  blocked.mockImplementation(actual.mkdir as never); pending.forEach(resolve => resolve());
  await vi.waitFor(async () => { expect(await auth.verifySessionCookieValue(cookie, env)).toBe(true); });
});

it("nonce fsync 실패를 반복해도 own 임시 파일을 남기지 않고 복구한다", async () => {
  vi.resetModules();
  const actual = await vi.importActual<typeof import("node:fs/promises")>("node:fs/promises");
  const mockedOpen = vi.fn(async (...args: Parameters<typeof actual.open>) => {
    const handle = await actual.open(...args);
    if (String(args[0]).includes(".nonce-")) handle.sync = async () => { throw new Error("unit fsync fault"); };
    return handle;
  });
  vi.doMock("node:fs/promises", () => ({ ...actual, open: mockedOpen }));
  const auth = await import("./auth");
  for (let index = 0; index < 3; index += 1) await expect(auth.createSessionCookieValue(null, env)).rejects.toThrow();
  expect(await actual.readdir(directory)).toEqual([]);
  mockedOpen.mockImplementation(actual.open);
  const cookie = await auth.createSessionCookieValue(null, env);
  expect(await auth.verifySessionCookieValue(cookie, env)).toBe(true);
});

it("temp 삭제도 실패하면 새 inode를 만들지 않고 삭제 회복 뒤 초기화를 재시도한다", async () => {
  vi.resetModules();
  const actual = await vi.importActual<typeof import("node:fs/promises")>("node:fs/promises");
  const mockedOpen = vi.fn(async (...args: Parameters<typeof actual.open>) => {
    const handle = await actual.open(...args);
    if (String(args[0]).includes(".nonce-")) handle.sync = async () => { throw new Error("unit fsync fault"); };
    return handle;
  });
  const mockedUnlink = vi.fn(async () => { throw new Error("unit unlink fault"); });
  vi.doMock("node:fs/promises", () => ({ ...actual, open: mockedOpen, unlink: mockedUnlink }));
  const auth = await import("./auth");
  for (let index = 0; index < 3; index += 1) await expect(auth.createSessionCookieValue(null, env)).rejects.toThrow();
  expect((await actual.readdir(directory)).filter(name => name.startsWith(".nonce-"))).toHaveLength(1);
  mockedOpen.mockImplementation(actual.open); mockedUnlink.mockImplementation(actual.unlink as never);
  const cookie = await auth.createSessionCookieValue(null, env);
  expect(await auth.verifySessionCookieValue(cookie, env)).toBe(true);
  expect((await actual.readdir(directory)).filter(name => name.startsWith(".nonce-"))).toHaveLength(0);
});

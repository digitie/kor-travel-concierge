import { createHash, randomBytes, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { link, lstat, mkdir, open, opendir, rmdir, unlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { isAbsolute, join } from "node:path";

type Env = Record<string, string | undefined>;
const HOUR_SECONDS = 3600;
const NONCE_BYTES = 64;

function stateDirectory(env: Env): string {
  const configured = env.KTC_UI_SESSION_STATE_DIR;
  const namespace = createHash("sha256").update(env.KTC_UI_SESSION_SECRET ?? "").digest("hex").slice(0, 24);
  const directory = configured ?? join(tmpdir(), `kor-travel-concierge-session-${namespace}`);
  if (!isAbsolute(directory)) throw new Error("Session state directory must be absolute");
  return directory;
}

async function privateDirectory(directory: string): Promise<void> {
  try { await mkdir(directory, { mode: 0o700 }); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
  const metadata = await lstat(directory);
  if (!metadata.isDirectory() || metadata.uid !== process.getuid?.() || (metadata.mode & 0o777) !== 0o700) {
    throw new Error("Session state directory is not private");
  }
}

async function syncDirectory(directory: string): Promise<void> {
  const handle = await open(directory, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  try { await handle.sync(); } finally { await handle.close(); }
}

async function readNonce(file: string): Promise<string> {
  const handle = await open(file, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const metadata = await handle.stat();
    if (!metadata.isFile() || metadata.uid !== process.getuid?.() || (metadata.mode & 0o777) !== 0o600 || metadata.size !== NONCE_BYTES) {
      throw new Error("Invalid session state nonce");
    }
    const buffer = Buffer.alloc(NONCE_BYTES + 1);
    let offset = 0;
    while (offset < buffer.length) {
      const { bytesRead } = await handle.read(buffer, offset, buffer.length - offset, offset);
      if (!bytesRead) break; offset += bytesRead;
    }
    if (offset !== NONCE_BYTES) throw new Error("Invalid session state nonce");
    const value = buffer.subarray(0, NONCE_BYTES).toString("utf8");
    if (!/^[a-f0-9]{64}$/.test(value)) throw new Error("Invalid session state nonce");
    return value;
  } finally { await handle.close(); }
}

// Linux UI 컨테이너의 Proxy와 Route Handler는 모듈 메모리를 공유한다고 가정하지 않는다.
// 같은 private 디렉터리의 nonce는 프로세스 재시작에도 유지된다. 디렉터리 자체가 새로
// 만들어지면 서명 namespace가 달라져 이전 쿠키를 전부 거절한다.
async function signingSecret(env: Env): Promise<string> {
  const directory = stateDirectory(env); await privateDirectory(directory);
  const file = join(directory, "nonce");
  let nonce: string;
  try { nonce = await readNonce(file); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    const temporary = join(directory, `.nonce-${randomUUID()}`);
    const handle = await open(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    try { await handle.writeFile(randomBytes(32).toString("hex")); await handle.sync(); }
    finally { await handle.close(); }
    try {
      try { await link(temporary, file); }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
    } finally { await unlink(temporary); }
    await syncDirectory(directory); nonce = await readNonce(file);
  }
  return `${env.KTC_UI_SESSION_SECRET}:${nonce}`;
}

function markerPath(directory: string, sessionId: string, expiry: number): string {
  const name = createHash("sha256").update(sessionId).digest("hex");
  return join(directory, `r-${Math.floor(expiry / HOUR_SECONDS)}`, name);
}

async function isRevoked(env: Env, sessionId: string, expiry: number): Promise<boolean> {
  const directory = stateDirectory(env); await privateDirectory(directory);
  try {
    // 어떠한 marker도 있으면 fail-closed한다. marker 원문이나 사용자 정보를 읽지 않는다.
    await lstat(markerPath(directory, sessionId, expiry)); return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    throw error;
  }
}

async function revoke(env: Env, sessionId: string, expiry: number, now: number): Promise<void> {
  const directory = stateDirectory(env); await privateDirectory(directory);
  const bucket = join(directory, `r-${Math.floor(expiry / HOUR_SECONDS)}`); await privateDirectory(bucket);
  const file = markerPath(directory, sessionId, expiry);
  try {
    const handle = await open(file, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
    try { await handle.sync(); } finally { await handle.close(); }
  } catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
  await syncDirectory(bucket); await syncDirectory(directory);
  // 만료 hour 버킷만 제거한다. 목록 전체를 메모리에 올리지 않는다.
  const entries = await opendir(directory);
  for await (const entry of entries) {
    const match = /^r-([0-9]{1,12})$/.exec(entry.name);
    if (match && (Number(match[1]) + 1) * HOUR_SECONDS <= now) {
      const expired = join(directory, entry.name); await privateDirectory(expired);
      // recursive rm도 내부 readdir 배열을 만들 수 있으므로 marker를 한 개씩 제거한다.
      try {
        const markers = await opendir(expired);
        for await (const marker of markers) {
          if (!/^[a-f0-9]{64}$/.test(marker.name) || !marker.isFile()) throw new Error("Invalid expired session marker");
          try { await unlink(join(expired, marker.name)); }
          catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
        }
        try { await rmdir(expired); }
        catch (error) { if (!["ENOENT", "ENOTEMPTY"].includes((error as NodeJS.ErrnoException).code ?? "")) throw error; }
      } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
    }
  }
}

const STATE_DEADLINE_MS = 2000;
const MAX_PENDING_STATE_OPERATIONS = 8;
let pendingStateOperations = 0;
async function boundedState<T>(run: () => Promise<T>): Promise<T> {
  // 각 고정 server bundle의 입장 상한이다. 인증 정본은 파일이며 전역 공유를 가정하지 않는다.
  if (pendingStateOperations >= MAX_PENDING_STATE_OPERATIONS) throw new Error("Session state busy");
  pendingStateOperations += 1;
  const operation = Promise.resolve().then(run).finally(() => { pendingStateOperations -= 1; });
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([operation, new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(new Error("Session state unavailable")), STATE_DEADLINE_MS);
    })]);
  } finally {
    clearTimeout(timer);
    // timeout은 파일 syscall 취소가 아니다. 원 작업이 settle할 때까지 슬롯을 유지한다.
  }
}

export function sessionSigningSecret(env: Env): Promise<string> {
  return boundedState(() => signingSecret(env));
}
export function sessionIsRevoked(env: Env, sessionId: string, expiry: number): Promise<boolean> {
  return boundedState(() => isRevoked(env, sessionId, expiry));
}
export function revokeSession(env: Env, sessionId: string, expiry: number, now: number): Promise<void> {
  return boundedState(() => revoke(env, sessionId, expiry, now));
}

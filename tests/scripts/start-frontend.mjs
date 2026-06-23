import { spawn, spawnSync } from "node:child_process";
import { rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const testsRoot = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(testsRoot, "..");
const frontendDir = path.join(repoRoot, "frontend");
const normalizeNextEnvScript = path.join(
  frontendDir,
  "scripts/normalize-next-env.mjs",
);
const backendPort = process.env.E2E_BACKEND_PORT ?? "18080";
const frontendPort = process.env.E2E_FRONTEND_PORT ?? "13100";
const e2eAdminUsername = process.env.KTC_E2E_ADMIN_USERNAME ?? "admin";
const e2eAdminPasswordHash =
  process.env.KTC_E2E_ADMIN_PASSWORD_HASH ??
  "pbkdf2_sha256$310000$a29yLXRyYXZlbC1jb25jaWVyZ2UtZTJlLXNhbHQ$Y0tGbvmqUxgWO8uumrRi27UGDXF2tb0w7RHtilooFAg";
const command = process.execPath;
process.env.NEXT_PUBLIC_VWORLD_SERVICE_KEY = "";
const args = [
  path.join(frontendDir, "node_modules", "next", "dist", "bin", "next"),
  "dev",
  "--hostname",
  "127.0.0.1",
  "--port",
  frontendPort,
];

// E2E는 hermetic하게 clean 캐시로 시작한다. 리네임/포트 churn이나 느린 파일시스템에서
// stale Turbopack `.next` 캐시가 손상되면 dev 서버가 panic("Next.js package not found")
// 후 페이지 reload loop에 빠져 E2E가 전부 실패한다(이슈 #70). 기동 직전 정리한다.
const nextCacheDir = path.join(frontendDir, ".next");
try {
  rmSync(nextCacheDir, { recursive: true, force: true });
  console.log(`[start-frontend] cleared stale Next cache: ${nextCacheDir}`);
} catch (error) {
  console.warn(
    `[start-frontend] failed to clear ${nextCacheDir}: ${error?.message ?? error}`,
  );
}

const child = spawn(
  command,
  args,
  {
    cwd: frontendDir,
    env: {
      ...process.env,
      // 브라우저는 same-origin BFF(`/api/v1/*`)로 호출한다(상대 경로).
      NEXT_PUBLIC_API_BASE_URL: "",
      // BFF Route Handler가 서버 사이드에서 E2E 백엔드로 프록시한다(APP_ENV=e2e 무인증).
      BACKEND_ORIGIN: `http://127.0.0.1:${backendPort}`,
      KTC_ADMIN_USERNAME: e2eAdminUsername,
      KTC_ADMIN_PASSWORD_HASH: e2eAdminPasswordHash,
      KTC_UI_SESSION_SECRET:
        process.env.KTC_E2E_UI_SESSION_SECRET ??
        "kor-travel-concierge-e2e-session-secret-32-bytes",
      KTC_ADMIN_PROXY_SECRET:
        process.env.KTC_E2E_ADMIN_PROXY_SECRET ??
        "kor-travel-concierge-e2e-admin-proxy-secret",
    },
    stdio: "inherit",
  },
);

let stopping = false;
let normalized = false;

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    stopChild(signal);
  });
}

function normalizeNextEnv() {
  if (normalized) {
    return;
  }
  normalized = true;
  spawnSync(process.execPath, [normalizeNextEnvScript], {
    cwd: frontendDir,
    stdio: "inherit",
  });
}

function stopChild(signal = "SIGTERM") {
  if (stopping) {
    return;
  }
  stopping = true;

  // Windows E2E 호스트에서는 next dev 자식 프로세스 트리를 taskkill로 정리해야
  // orphan이 남지 않는다(ADR-23 E2E 예외).
  if (process.platform === "win32" && child.pid) {
    spawnSync("taskkill", ["/pid", String(child.pid), "/t", "/f"], {
      stdio: "ignore",
    });
    normalizeNextEnv();
    process.exit(0);
  }

  child.kill(signal);
  setTimeout(() => {
    if (!child.killed) {
      child.kill("SIGKILL");
    }
    normalizeNextEnv();
    process.exit(0);
  }, 3_000).unref();
}

child.on("exit", (code, signal) => {
  normalizeNextEnv();
  if (stopping) {
    return;
  }
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});

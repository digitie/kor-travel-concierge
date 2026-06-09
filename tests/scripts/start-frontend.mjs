import { spawn, spawnSync } from "node:child_process";
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

const child = spawn(
  command,
  args,
  {
    cwd: frontendDir,
    env: {
      ...process.env,
      NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${backendPort}`,
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

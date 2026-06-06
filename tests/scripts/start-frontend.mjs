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
const command = process.platform === "win32" ? "cmd.exe" : "npm";
const args =
  process.platform === "win32"
    ? [
        "/d",
        "/s",
        "/c",
        `npm run dev -- --hostname 127.0.0.1 --port ${frontendPort}`,
      ]
    : [
        "run",
        "dev",
        "--",
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
      NEXT_PUBLIC_VWORLD_SERVICE_KEY: "",
    },
    stdio: "inherit",
  },
);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    child.kill(signal);
  });
}

function normalizeNextEnv() {
  spawnSync(process.execPath, [normalizeNextEnvScript], {
    cwd: frontendDir,
    stdio: "inherit",
  });
}

child.on("exit", (code, signal) => {
  normalizeNextEnv();
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});

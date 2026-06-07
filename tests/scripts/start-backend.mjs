import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const testsRoot = path.resolve(scriptDir, "..");
const repoRoot = path.resolve(testsRoot, "..");
const backendDir = path.join(repoRoot, "backend");
const tmpDir = path.join(testsRoot, ".tmp");
const dbPath = path.join(tmpDir, "e2e.db");
const backendPort = process.env.E2E_BACKEND_PORT ?? "18080";
const frontendPort = process.env.E2E_FRONTEND_PORT ?? "13100";
const frontendOrigin = `http://127.0.0.1:${frontendPort}`;

mkdirSync(tmpDir, { recursive: true });
for (const suffix of ["", "-wal", "-shm"]) {
  rmSync(`${dbPath}${suffix}`, { force: true });
}

const python = resolvePython();
const child = spawn(
  python,
  [
    "-m",
    "uvicorn",
    "main:app",
    "--host",
    "127.0.0.1",
    "--port",
    backendPort,
  ],
  {
    cwd: backendDir,
    env: {
      ...process.env,
      DATABASE_URL: "sqlite+aiosqlite:///../tests/.tmp/e2e.db",
      NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${backendPort}`,
      CORS_ALLOW_ORIGINS: [
        frontendOrigin,
        `http://localhost:${frontendPort}`,
      ].join(","),
      RUSTFS_ENDPOINT: "http://127.0.0.1:19003",
      RUSTFS_PUBLIC_BASE_URL: "http://127.0.0.1:19003/krtour-map",
      RUSTFS_CONSOLE_URL: "http://127.0.0.1:19004",
      RUSTFS_BUCKET_RAW_VIDEOS: "krtour-map",
      RUSTFS_BUCKET_SUBTITLES: "krtour-map",
      RUSTFS_BUCKET_FRAMES: "krtour-map",
      RUSTFS_OBJECT_PREFIX: "features",
      RUSTFS_REGION: "us-east-1",
    },
    stdio: "inherit",
  },
);

forwardSignals(child);

function resolvePython() {
  const local = path.join(
    backendDir,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  if (existsSync(local)) {
    return local;
  }
  return process.platform === "win32" ? "python.exe" : "python";
}

function forwardSignals(processToStop) {
  let stopping = false;

  function stop(signal = "SIGTERM") {
    if (stopping) {
      return;
    }
    stopping = true;

    if (process.platform === "win32" && processToStop.pid) {
      spawnSync("taskkill", ["/pid", String(processToStop.pid), "/t", "/f"], {
        stdio: "ignore",
      });
      process.exit(0);
    }

    processToStop.kill(signal);
    setTimeout(() => {
      if (!processToStop.killed) {
        processToStop.kill("SIGKILL");
      }
      process.exit(0);
    }, 3_000).unref();
  }

  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => {
      stop(signal);
    });
  }
  processToStop.on("exit", (code, signal) => {
    if (stopping) {
      return;
    }
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 0);
  });
}

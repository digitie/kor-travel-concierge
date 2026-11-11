import { pbkdf2Sync, randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("../../frontend/", import.meta.url));
const salt = randomBytes(16);
const hash = pbkdf2Sync(process.env.KTC_COMMON_UI_TEST_PASSWORD, salt, 310_000, 32, "sha256");
const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", "13119"], {
  cwd: frontend,
  env: {
    ...process.env,
    BACKEND_ORIGIN: "http://127.0.0.1:1",
    KTC_ADMIN_USERNAME: "test-operator",
    KTC_ADMIN_PASSWORD_HASH: ["pbkdf2_sha256", "310000", salt.toString("base64url"), hash.toString("base64url")].join("$"),
    KTC_UI_SESSION_SECRET: randomBytes(48).toString("hex"),
    KTC_UI_SESSION_STATE_DIR: fileURLToPath(new URL("../../.git/common-ui-session/", import.meta.url)),
  },
  stdio: "inherit",
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("exit", code => process.exit(code ?? 1));

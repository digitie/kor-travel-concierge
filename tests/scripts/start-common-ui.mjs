import { pbkdf2Sync, randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

// 사용: node scripts/start-common-ui.mjs [port] [map-key-env]
// - port: 기본 13119(키 없는 지도). 같은 build를 다른 port로 한 번 더 띄울 수 있다.
// - map-key-env: 실행 시 지도 키(KTC_VWORLD_BROWSER_KEY, T-212)로 넘길 값이 든 env 이름. 없으면 키 없음.
//   상위 셸의 KTC_VWORLD_BROWSER_KEY는 쓰지 않는다 — 어느 서버가 키를 갖는지 시험이 정한다.
const [port = "13119", mapKeyEnv] = process.argv.slice(2);
const frontend = fileURLToPath(new URL("../../frontend/", import.meta.url));
const sessionStateDirectory = fileURLToPath(
  new URL(port === "13119" ? "../../.git/common-ui-session/" : `../../.git/common-ui-session-${port}/`, import.meta.url),
);
// git archive에는 .git이 없다. 상태 디렉터리 자체의 private 권한 검사는 앱이 소유한다.
mkdirSync(dirname(sessionStateDirectory), { recursive: true, mode: 0o700 });

const salt = randomBytes(16);
const hash = pbkdf2Sync(process.env.KTC_COMMON_UI_TEST_PASSWORD, salt, 310_000, 32, "sha256");
const child = spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", port], {
  cwd: frontend,
  env: {
    ...process.env,
    BACKEND_ORIGIN: "http://127.0.0.1:1",
    KTC_ADMIN_USERNAME: "test-operator",
    KTC_ADMIN_PASSWORD_HASH: ["pbkdf2_sha256", "310000", salt.toString("base64url"), hash.toString("base64url")].join("$"),
    KTC_UI_SESSION_SECRET: randomBytes(48).toString("hex"),
    KTC_UI_SESSION_STATE_DIR: sessionStateDirectory,
    KTC_VWORLD_BROWSER_KEY: mapKeyEnv ? (process.env[mapKeyEnv] ?? "") : "",
  },
  stdio: "inherit",
});
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("exit", code => process.exit(code ?? 1));

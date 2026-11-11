import { randomBytes } from "node:crypto";
import { defineConfig } from "@playwright/test";

// 이 프로세스의 격리 UI에만 사용하는 일회성 인증값. 로그/저장소에 기록하지 않는다.
process.env.KTC_COMMON_UI_TEST_PASSWORD ??= randomBytes(24).toString("hex");
export default defineConfig({
  testDir: "./e2e",
  testMatch: "common-ui.spec.ts",
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  outputDir: "./test-results/common-ui",
  reporter: "list",
  // 격리 Chromium에서 실제 WebGL 마커 계약을 검증하기 위한 소프트웨어 렌더러다.
  use: {
    launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] },
    baseURL: "http://127.0.0.1:13119",
    viewport: { width: 1440, height: 1000 },
  },
  webServer: process.env.KTC_COMMON_UI_SKIP_SERVER === "1" ? undefined : {
    command: "node scripts/start-common-ui.mjs",
    url: "http://127.0.0.1:13119/login",
    reuseExistingServer: false,
    timeout: 90_000,
  },
});

import { defineConfig, devices } from '@playwright/test';

/**
 * Linux / Docker(및 Windows WSL2) 환경 Playwright E2E 테스트 기본 설정
 */
const frontendPort = process.env.E2E_FRONTEND_PORT ?? '13100';
const backendPort = process.env.E2E_BACKEND_PORT ?? '18080';
const baseURL = process.env.E2E_FRONTEND_URL ?? `http://127.0.0.1:${frontendPort}`;
const backendURL = process.env.E2E_API_BASE_URL ?? `http://127.0.0.1:${backendPort}`;
const nodeCommand = quoteForShell(process.execPath);
const skipWebServer =
  process.env.E2E_SKIP_WEBSERVER === '1' || process.env.KTC_LIVE_E2E === '1';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // E2E seed와 shared PostGIS 테스트 DB 충돌을 피하기 위해 순차 실행
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: skipWebServer
    ? undefined
    : [
        {
          command: `${nodeCommand} ./scripts/start-backend.mjs`,
          url: `${backendURL}/health`,
          timeout: 120_000,
          reuseExistingServer: !process.env.CI,
        },
        {
          command: `${nodeCommand} ./scripts/start-frontend.mjs`,
          url: baseURL,
          timeout: 120_000,
          reuseExistingServer: !process.env.CI,
        },
      ],
});

function quoteForShell(value: string) {
  return `"${value.replace(/"/g, '\\"')}"`;
}

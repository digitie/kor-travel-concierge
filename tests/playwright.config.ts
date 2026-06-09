import { defineConfig, devices } from '@playwright/test';

/**
 * Linux / Docker(및 Windows WSL2) 환경 Playwright E2E 테스트 기본 설정
 */
const frontendPort = process.env.E2E_FRONTEND_PORT ?? '13100';
const backendPort = process.env.E2E_BACKEND_PORT ?? '18080';
const baseURL = process.env.E2E_FRONTEND_URL ?? `http://127.0.0.1:${frontendPort}`;
const backendURL = process.env.E2E_API_BASE_URL ?? `http://127.0.0.1:${backendPort}`;
const nodeCommand = quoteForShell(process.execPath);

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // 로컬 SQLite + SpatiaLite 락 충돌 방지를 위해 순차적 실행 권장
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

  webServer: [
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

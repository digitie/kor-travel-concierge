import { defineConfig, devices } from '@playwright/test';

/**
 * Windows 환경 Playwright E2E 테스트 기본 설정
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1, // 로컬 SQLite + SpatiaLite 락 충돌 방지를 위해 순차적 실행 권장
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // 로컬 개발/평가 시 서버 자동 구동 설정 예제
  // webServer: [
  //   {
  //     command: 'cd ../backend && .venv\\Scripts\\activate && python main.py',
  //     port: 8000,
  //     reuseExistingServer: !process.env.CI,
  //   },
  //   {
  //     command: 'cd ../frontend && npm run dev',
  //     port: 3000,
  //     reuseExistingServer: !process.env.CI,
  //   }
  // ]
});

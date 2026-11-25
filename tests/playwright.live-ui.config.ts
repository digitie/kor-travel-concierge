import { defineConfig } from '@playwright/test';

// 운영 기본값과 seed/webServer를 두지 않는다. 실행자가 명시한 공개 URL만 시험한다.
if (process.env.KTC_LIVE_E2E !== '1' || !process.env.E2E_BASE_URL ||
    !process.env.E2E_ADMIN_USERNAME || !process.env.E2E_ADMIN_PASSWORD) {
  throw new Error('live UI 실행에는 KTC_LIVE_E2E=1, E2E_BASE_URL과 비공개 관리자 환경변수가 필요합니다.');
}
// 브라우저 프로세스에는 자격 값을 물려주지 않는다(시험 코드는 runner 프로세스의 env로 읽는다).
const browserEnv = Object.fromEntries(Object.entries(process.env)
  .filter((entry): entry is [string, string] => entry[1] !== undefined && !/^E2E_ADMIN_/.test(entry[0])));
export default defineConfig({
  testDir: './e2e',
  // 자격이 틀리면 91건이 저마다 로그인에 실패해 운영 로그인 잠금(10분 5회)을 건다. 먼저 한 번만 확인한다.
  globalSetup: './e2e/live-login-preflight.ts',
  // 아래 다섯 파일은 운영 write를 브라우저에서 막는 읽기 전용 시험이다(live-ui-fixtures 또는 파일 안 guard).
  // 운영 상태를 바꾸는 시험은 `*.write.live.spec.ts`로 두고 KTC_LIVE_E2E_WRITE=1일 때만 수집한다
  // (scripts/n150-live-ui-e2e.sh).
  testMatch: ['live-auth-navigation.spec.ts', 'live-forms-actions.spec.ts',
    'live-operations.spec.ts', 'live-results-review.spec.ts', 'map-loading-recovery.spec.ts',
    ...(process.env.KTC_LIVE_E2E_WRITE === '1' ? ['*.write.live.spec.ts'] : [])],
  timeout: 75_000, expect: { timeout: 15_000 }, workers: 1, retries: 0,
  outputDir: './test-results/live-ui', reporter: [['list'], ['json', { outputFile: './test-results/live-ui/report.json' }]],
  use: { baseURL: process.env.E2E_BASE_URL, headless: true,
    viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure', trace: 'off',
    launchOptions: { env: browserEnv } },
});

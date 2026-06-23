import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const backendURL = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:18080';
const repoRoot = path.resolve(__dirname, '../..');
const backendDir = path.join(repoRoot, 'backend');
const seedScript = path.join(repoRoot, 'tests/scripts/seed_e2e.py');

test.describe('Kor Travel Concierge E2E 검증', () => {
  test.beforeEach(() => {
    seedE2EData();
  });

  test('결과 화면이 장소 목록·지도·실행 큐·내비를 렌더링한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);

    await expectSeedReady(page);
    await page.goto('/');

    await expect(page).toHaveTitle(/Kor Travel Concierge/);
    // 결과(/) = 확정 장소 목록 + 지도 + 간단 실행 큐 상태(상세는 /collect·/review로 분리, T-097+)
    const placesRegion = page.getByRole('region', { name: '장소 목록' });
    await expect(placesRegion).toBeVisible();
    // 장소 행 버튼(이름 포함)과 ⓘ "월정리 해변 상세" 버튼 둘 다 매칭되므로 행 버튼(first)만.
    await expect(
      placesRegion.getByRole('button', { name: /월정리 해변/ }).first(),
    ).toBeVisible();
    await expect(page.locator('#vworld-map-container')).toBeVisible();
    await expect(page.locator('#vworld-map-container')).toHaveAttribute(
      'data-status',
      'fallback',
    );
    await expect(page.getByText('실행 큐').first()).toBeVisible();
    // 멀티페이지 내비(결과/수집/검수) — 헤더 nav 안의 링크 텍스트로 확인
    const nav = page.locator('header nav');
    await expect(nav.getByText('수집')).toBeVisible();
    await expect(nav.getByText('검수')).toBeVisible();

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('수집 화면에서 수집 시작 시 job_id·pending을 표시한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.goto('/collect');

    await page.locator('#harvest-target').fill('제주 카페');
    await page.locator('#harvest-max-videos').fill('3');
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/harvest') &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: /수집 시작/ }).click();

    const response = await responsePromise;
    expect(response.ok()).toBeTruthy();
    const job = (await response.json()) as { job_id: string; state: string };
    expect(job.state).toBe('pending');

    const statusPanel = page.locator('section[aria-live="polite"]');
    await expect(statusPanel).toContainText(job.job_id);
    await expect(statusPanel).toContainText('pending');

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('Deep Research(상세 모달)와 검수 저장이 API·UI에 반영된다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await expectSeedReady(page);

    // Part A: 결과 화면에서 장소 상세 모달을 열고 Deep Research(상세 모달로 이동, T-107)
    await page.goto('/');
    await page.getByRole('button', { name: '월정리 해변 상세' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    const deepResearchResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/destinations/') &&
        response.url().endsWith('/deep-research') &&
        response.request().method() === 'POST',
    );
    await dialog.getByRole('button', { name: /Deep Research/ }).click();
    expect((await deepResearchResponse).ok()).toBeTruthy();
    await expect
      .poll(async () => {
        const response = await page.request.get(`${backendURL}/api/v1/runs?limit=12`);
        const runs = (await response.json()) as Array<{ job_type: string }>;
        return runs.some((run) => run.job_type === 'deep_research');
      })
      .toBe(true);

    // Part B: 검수 화면에서 후보를 확정 저장
    await page.goto('/review');
    await page.getByRole('button', { name: /성산 일출봉 카페/ }).first().click();
    await page.getByLabel('확정 장소명').fill('성산 일출봉 카페');
    await page.getByLabel('위도').fill('33.4581');
    await page.getByLabel('경도').fill('126.9425');
    await page.getByLabel('카테고리').fill('카페');
    const resolveResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/destinations/unmatched/') &&
        response.url().endsWith('/resolve') &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '저장' }).click();
    expect((await resolveResponse).ok()).toBeTruthy();

    await expect
      .poll(async () => {
        const response = await page.request.get(`${backendURL}/api/v1/destinations/unmatched`);
        const candidates = (await response.json()) as unknown[];
        return candidates.length;
      })
      .toBe(0);

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('설정 화면에서 AI 엔진을 저장한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.goto('/settings');

    await expect(page.locator('#ai-engine-select')).toBeVisible();
    await page.locator('#ai-engine-select').click();
    await page.getByRole('option', { name: 'gemini-2.0-flash', exact: true }).click();
    await page.locator('#settings-save-button').click();

    await expect(page.locator('#success-toast')).toBeVisible();
    await expect
      .poll(async () => {
        const response = await page.request.get(`${backendURL}/api/v1/settings`);
        const settings = (await response.json()) as Record<string, string>;
        return settings.gemini_engine_version;
      })
      .toBe('gemini-2.0-flash');

    expectRelevantConsoleErrors(errors).toEqual([]);
  });
});

function seedE2EData() {
  const databaseUrl =
    process.env.KTC_E2E_DATABASE_URL ??
    process.env.KTC_TEST_PG_DSN ??
    process.env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error(
      'E2E seed에는 KTC_E2E_DATABASE_URL 또는 KTC_TEST_PG_DSN이 필요합니다.',
    );
  }
  execFileSync(resolvePython(), [seedScript], {
    cwd: backendDir,
    env: {
      ...process.env,
      DATABASE_URL: databaseUrl,
      PYTHONPATH: backendDir,
    },
    stdio: 'inherit',
  });
}

async function expectSeedReady(page: Page) {
  await expect
    .poll(
      async () => {
        const [placesResponse, candidatesResponse, auditResponse] = await Promise.all([
          page.request.get(`${backendURL}/api/v1/destinations`),
          page.request.get(`${backendURL}/api/v1/destinations/unmatched`),
          page.request.get(`${backendURL}/api/v1/audit-logs?limit=10`),
        ]);
        if (!placesResponse.ok() || !candidatesResponse.ok() || !auditResponse.ok()) {
          return 'not-ready';
        }

        const [places, candidates, audits] = (await Promise.all([
          placesResponse.json(),
          candidatesResponse.json(),
          auditResponse.json(),
        ])) as [unknown[], unknown[], unknown[]];

        return `${places.length}:${candidates.length}:${audits.length}`;
      },
      { timeout: 10_000 },
    )
    .toBe('1:1:1');
}

function resolvePython() {
  const local = path.join(
    backendDir,
    '.venv',
    process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
  );
  if (existsSync(local)) {
    return local;
  }
  return process.platform === 'win32' ? 'python.exe' : 'python';
}

function collectConsoleErrors(page: Page) {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') {
      errors.push(message.text());
    }
  });
  page.on('pageerror', (error) => errors.push(error.message));
  return errors;
}

function expectRelevantConsoleErrors(errors: string[]) {
  return expect(errors.filter(isRelevantConsoleError));
}

function isRelevantConsoleError(message: string) {
  if (
    message.includes('favicon') ||
    message.includes('ResizeObserver loop completed')
  ) {
    return false;
  }

  return [
    'Hydration failed',
    'ReferenceError',
    'SyntaxError',
    'TypeError',
    'Unhandled',
    'Failed to fetch',
    'Internal Server Error',
  ].some((pattern) => message.includes(pattern));
}

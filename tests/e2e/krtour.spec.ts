import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const backendURL = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:18080';
const repoRoot = path.resolve(__dirname, '../..');
const backendDir = path.join(repoRoot, 'backend');
const seedScript = path.join(repoRoot, 'tests/scripts/seed_e2e.py');

test.describe('KRTour AI Agent E2E 검증', () => {
  test.beforeEach(() => {
    seedE2EData();
  });

  test('메인 화면이 장소·지도·검수 큐·운영 패널을 렌더링한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);

    await expectSeedReady(page);
    await page.goto('/');

    const placesRegion = page.getByRole('region', { name: '장소 목록' });
    const reviewRegion = page.getByRole('region', { name: '검수 큐' });
    const operationsRegion = page.getByRole('region', { name: '운영 패널' });
    const sidebar = page.locator('#destination-list');

    await expect(page).toHaveTitle(/KRTour AI Agent/);
    await expect(page.locator('#destination-list')).toBeVisible();
    await expect(page.locator('#vworld-map-container')).toBeVisible();
    await expect(page.locator('#vworld-map-container')).toHaveAttribute(
      'data-status',
      'fallback',
    );
    await expect(sidebar.getByText('실행 큐')).toBeVisible();
    await expect(sidebar.getByText('harvest · 부산 맛집')).toBeVisible();
    await expect(placesRegion.getByRole('heading', { name: '장소' })).toBeVisible();
    await expect(placesRegion.getByRole('button', { name: /월정리 해변/ })).toBeVisible();
    await expect(reviewRegion.getByRole('heading', { name: '검수 큐' })).toBeVisible();
    await expect(reviewRegion.getByRole('button', { name: /성산 일출봉 카페/ })).toBeVisible();
    await expect(operationsRegion.getByRole('heading', { name: '운영' })).toBeVisible();
    await expect(operationsRegion.getByText('실행 큐')).toBeVisible();
    await expect(operationsRegion.getByText('harvest · 부산 맛집').first()).toBeVisible();
    await expect(operationsRegion.getByText(/검색을 실행 중/).first()).toBeVisible();
    await expect(operationsRegion.getByText('MCP/웹 쓰기 로그')).toBeVisible();
    await expect(operationsRegion.getByText('place.correct')).toBeVisible();

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('수집 시작 후 job_id와 pending 상태를 표시한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await expectSeedReady(page);
    await page.goto('/');

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

  test('Deep Research와 검수 후보 저장이 API와 UI에 반영된다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await expectSeedReady(page);
    await page.goto('/');

    const placesRegion = page.getByRole('region', { name: '장소 목록' });
    const reviewRegion = page.getByRole('region', { name: '검수 큐' });

    await placesRegion.getByRole('button', { name: /월정리 해변/ }).click();
    const deepResearchResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/destinations/') &&
        response.url().endsWith('/deep-research') &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: /Deep Research/ }).click();
    expect((await deepResearchResponse).ok()).toBeTruthy();
    await expect
      .poll(async () => {
        const response = await page.request.get(`${backendURL}/api/v1/runs?limit=12`);
        const runs = (await response.json()) as Array<{ job_type: string }>;
        return runs.some((run) => run.job_type === 'deep_research');
      })
      .toBe(true);

    await reviewRegion.getByRole('button', { name: /성산 일출봉 카페/ }).click();
    await page.getByLabel('보정 장소명').fill('성산 일출봉 카페');
    await page.getByLabel('보정 위도').fill('33.4581');
    await page.getByLabel('보정 경도').fill('126.9425');
    await page.getByLabel('보정 카테고리').fill('카페');
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
    await expect(reviewRegion.getByRole('button', { name: /성산 일출봉 카페/ })).toHaveCount(0);
    await expect(placesRegion.getByRole('button', { name: /성산 일출봉 카페/ })).toBeVisible();

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('설정 페이지에서 Gemini 엔진 설정을 저장한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.goto('/settings');

    await expect(page.locator('#gemini-engine-select')).toBeVisible();
    await page.locator('#gemini-engine-select').click();
    await page.getByRole('option', { name: 'gemini-1.5-pro' }).click();
    await page.locator('#settings-save-button').click();

    await expect(page.locator('#success-toast')).toBeVisible();
    await expect
      .poll(async () => {
        const response = await page.request.get(`${backendURL}/api/v1/settings`);
        const settings = (await response.json()) as Record<string, string>;
        return settings.gemini_engine_version;
      })
      .toBe('gemini-1.5-pro');

    expectRelevantConsoleErrors(errors).toEqual([]);
  });
});

function seedE2EData() {
  const databaseUrl =
    process.env.KRTOUR_AI_AGENT_E2E_DATABASE_URL ??
    process.env.KRTOUR_AI_AGENT_TEST_PG_DSN ??
    process.env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error(
      'E2E seed에는 KRTOUR_AI_AGENT_E2E_DATABASE_URL 또는 KRTOUR_AI_AGENT_TEST_PG_DSN이 필요합니다.',
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

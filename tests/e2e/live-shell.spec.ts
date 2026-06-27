import { expect, test, type Page } from '@playwright/test';

const liveEnabled = process.env.KTC_LIVE_E2E === '1';
const e2eAdminUsername = process.env.KTC_E2E_ADMIN_USERNAME ?? 'admin';
const e2eAdminPassword = process.env.KTC_E2E_ADMIN_PASSWORD ?? '';

test.describe('n150 live UI 셸 검증', () => {
  test.skip(!liveEnabled, 'KTC_LIVE_E2E=1 일 때만 n150 live UI를 검증한다.');

  test('메뉴, 상단 작업 상태, 상태 페이지, 설정 페이지가 동작한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await loginAsAdmin(page, '/');

    await expect(page.getByRole('heading', { name: '결과', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: /결과/ }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: /수집/ }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: /검수/ }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: /상태/ }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: /설정/ }).first()).toBeVisible();

    const statusLink = page.getByRole('link', { name: /작업 상태/ }).first();
    await expect(statusLink).toBeVisible();
    await statusLink.click();
    await page.waitForURL('**/status');
    await expect(page.getByRole('heading', { name: '상태', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: '실행 큐 상세' })).toBeVisible();
    await expect(page.getByRole('heading', { name: '최근 작업' })).toBeVisible();
    await expect(page.getByRole('heading', { name: '저장소 상세' })).toBeVisible();

    await page.getByRole('link', { name: /설정/ }).first().click();
    await page.waitForURL('**/settings');
    await expect(page.getByRole('heading', { name: '설정', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'AI 엔진', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'API 키', exact: true })).toBeVisible();
    await expect(
      page.getByRole('heading', { name: '외부 공개 API 키', exact: true }),
    ).toBeVisible();
    await expect(page.locator('#ai-engine-select')).toBeVisible();

    await page.getByRole('link', { name: /검수/ }).first().click();
    await page.waitForURL('**/review');
    await expect(page.getByRole('heading', { name: '검수 큐', exact: true })).toBeVisible();

    await page.getByRole('link', { name: /수집/ }).first().click();
    await page.waitForURL('**/collect');
    await expect(page.getByRole('heading', { name: '수집', exact: true })).toBeVisible();

    expectRelevantConsoleErrors(errors).toEqual([]);
  });
});

async function loginAsAdmin(page: Page, nextPath: string) {
  if (!e2eAdminPassword) {
    throw new Error('KTC_E2E_ADMIN_PASSWORD가 필요합니다.');
  }
  await page.goto(`/login?next=${encodeURIComponent(nextPath)}`);
  await page.locator('#login-username').fill(e2eAdminUsername);
  await page.locator('#login-password').fill(e2eAdminPassword);
  await page.getByRole('button', { name: '로그인' }).click();
  await page.waitForURL((url) => url.pathname === nextPath, { timeout: 10_000 });
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
    message.includes('ResizeObserver loop completed') ||
    message.includes('Failed to load resource: the server responded with a status of 401')
  ) {
    return false;
  }

  return [
    'Hydration failed',
    'ReferenceError',
    'SyntaxError',
    'TypeError',
    'Unhandled',
    'Internal Server Error',
  ].some((pattern) => message.includes(pattern));
}

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

  test('수집 반복 작업 테이블과 수정 다이얼로그가 누적 정보를 보여준다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await loginAsAdmin(page, '/collect');

    await expect(page.getByRole('heading', { name: '수집', exact: true })).toBeVisible();
    const queueRegion = page.getByRole('region', { name: '실행 큐' });
    await expect(queueRegion).toBeVisible();
    await expect(queueRegion.getByText('실행 큐')).toBeVisible();

    const jobsRegion = page.getByRole('region', { name: '작업' });
    await expect(jobsRegion.getByRole('tab', { name: /반복/ })).toBeVisible();
    await expect(jobsRegion.getByRole('columnheader', { name: '대상' }).first()).toBeVisible();
    await expect(jobsRegion.getByRole('columnheader', { name: '주기' })).toBeVisible();
    await expect(jobsRegion.getByRole('columnheader', { name: '누적' })).toBeVisible();
    await expect(jobsRegion.getByRole('columnheader', { name: '일정' })).toBeVisible();
    await expect(jobsRegion.getByRole('columnheader', { name: '액션' })).toBeVisible();

    await jobsRegion.getByRole('button', { name: '수정' }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: /작업 수정/ })).toBeVisible();
    await expect(dialog.getByText('반복 작업 수정')).toHaveCount(0);
    await expect(dialog.getByText('누적 수집 영상')).toBeVisible();
    await expect(dialog.getByText('실행 횟수')).toBeVisible();
    await expect(dialog.getByText('마지막 영상 날짜')).toBeVisible();
    await expect(dialog.getByText('다음 실행')).toBeVisible();
    await expect(dialog.locator('#recurring-edit-interval')).toBeVisible();
    await expect(dialog.locator('#recurring-edit-count')).toBeVisible();
    await expect(dialog.locator('#recurring-edit-max-videos')).toBeVisible();
    await expect(dialog.getByText('강제 다운로드 (전체 재수집)')).toBeVisible();
    await expect(dialog.getByText('저장 직후 한 번만 전체 재수집 작업을 실행합니다.')).toBeVisible();
    await dialog.getByRole('button', { name: '닫기' }).first().click();

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

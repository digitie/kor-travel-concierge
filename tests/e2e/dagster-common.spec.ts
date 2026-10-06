import { test, expect, type Page } from '@playwright/test';

test.skip(process.env.KTC_LIVE_E2E !== '1', '격리한 live Dagster/API와 관리자 자격이 필요합니다.');
const username = process.env.E2E_ADMIN_USERNAME ?? '';
const password = process.env.E2E_ADMIN_PASSWORD ?? '';
const failureRun = process.env.E2E_DAGSTER_FAILURE_RUN ?? '';
const summaryPath = '/api/v1/admin/dagster/summary';

async function login(page: Page) {
  expect(username && password && failureRun).toBeTruthy();
  await page.goto('/dagster');
  await expect(page).toHaveURL(/\/login\?next=/);
  await page.getByLabel('아이디', { exact: true }).fill(username);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  const response = page.waitForResponse(r => r.url().endsWith(summaryPath));
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  const actual = await response;
  expect(actual.status()).toBe(200);
  const body = await actual.json();
  expect(body.status).toBe('ok');
  expect(body.snapshot.repositories).toHaveLength(1);
  expect(body.snapshot.repositories[0].locationName).toBe('ktc.dagster.definitions');
  expect(body.snapshot.runs.some((run: {runId: string; status: string}) => run.runId === failureRun && run.status === 'FAILURE')).toBe(true);
  await expect(page.getByTestId('concierge-common-dagster')).toBeVisible();
  return body;
}

test('실제 native 실행, 공용 메뉴, 장애 복구와 인증 수명', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const actual = await login(page);
  await expect(page.getByRole('link', { name: 'Dagster', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.getByRole('button', { name: '좌측 메뉴 접기', exact: true }).click();
  await page.getByRole('button', { name: '좌측 메뉴 펼치기', exact: true }).click();
  await page.getByLabel('실행 검색', { exact: true }).fill(failureRun);
  await page.getByRole('button', { name: new RegExp(`실행 상세: .*${failureRun}`) }).click();
  const detail = page.getByTestId('concierge-selected-run');
  await expect(detail).toContainText(failureRun);
  await expect(detail).toContainText('FAILURE');
  const run = actual.snapshot.runs.find((item: {runId: string}) => item.runId === failureRun);
  await expect(detail).toContainText(`시간 상한: ${run.maxRuntimeSeconds}초`);
  await expect(detail.getByRole('link', { name: /수집 작업/ })).toHaveAttribute('href', `/jobs/${run.domainRunId}`);
  const popupPromise = page.waitForEvent('popup');
  await detail.getByRole('link', { name: 'Dagster 실행 로그', exact: true }).click();
  const popup = await popupPromise;
  await expect(popup).toHaveURL(new RegExp(`/runs/${failureRun}`));
  await expect(popup.locator('body')).toContainText('concierge_batch', { timeout: 30000 });
  await popup.close();
  await page.screenshot({ path: testInfo.outputPath('dagster-desktop.png'), fullPage: true });

  // 실제 API/schema 검증 이후 브라우저 응답만 바꿔 장애 표시를 검증한다.
  await page.route(`**${summaryPath}`, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({status: 'degraded', snapshot: null}) }));
  await page.getByRole('button', { name: '새로고침', exact: true }).click();
  await expect(page.getByTestId('concierge-common-dagster').getByRole('alert')).toContainText('마지막 정상 조회');
  await expect(detail).toContainText(failureRun);
  await page.unroute(`**${summaryPath}`);
  await page.getByRole('button', { name: '다시 시도', exact: true }).click();
  await expect(page.getByTestId('concierge-common-dagster').getByRole('alert')).toHaveCount(0);
  await expect(detail).toContainText(failureRun);

  await page.route(`**${summaryPath}`, route => route.fulfill({ status: 401, body: '{}' }));
  await page.getByRole('button', { name: '새로고침', exact: true }).click();
  await expect(detail).toHaveCount(0);
  await expect(page.getByLabel('실행 검색', { exact: true })).toHaveCount(0);
  await page.unroute(`**${summaryPath}`);
  await page.getByRole('button', { name: '다시 시도', exact: true }).click();
  await expect(page.getByTestId('concierge-common-dagster').getByRole('alert')).toHaveCount(0);
  await expect(page.getByTestId('concierge-selected-run')).toHaveCount(0);
  await page.getByRole('button', { name: '로그아웃', exact: true }).filter({ visible: true }).click();
  await expect(page).toHaveURL(/\/login/);
  const denied = await page.request.get(summaryPath);
  expect(denied.status()).toBe(401);
  await page.goto('/dagster');
  await expect(page).toHaveURL(/\/login\?next=/);
});

test('모바일 실행 선택과 기존 작업 화면 이동', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.getByLabel('실행 검색', { exact: true }).fill(failureRun);
  await page.getByRole('button', { name: new RegExp(`실행 상세: .*${failureRun}`) }).click();
  await expect(page.getByTestId('concierge-selected-run')).toContainText(failureRun);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('dagster-mobile.png'), fullPage: true });
  await page.getByTestId('concierge-selected-run').getByRole('link', { name: /수집 작업/ }).click();
  await expect(page).toHaveURL(/\/jobs\/\d+/);
  await expect(page.getByRole('link', { name: '작업', exact: true })).toHaveAttribute('aria-current', 'page');
});

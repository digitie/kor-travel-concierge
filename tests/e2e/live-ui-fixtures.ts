import { test as base, expect, type Page, type TestInfo } from '@playwright/test';

type Observations = { blocked: string[]; errors: string[]; failures: string[]; providers: string[]; allowed: Set<string> };
export const test = base.extend<{ observations: Observations }>({
  observations: [async ({ page }, use, info) => {
    const state: Observations = { blocked: [], errors: [], failures: [], providers: [], allowed: new Set() };
    page.on('pageerror', error => state.errors.push(`${error.name}: ${error.message}`));
    page.on('requestfailed', request => {
      const path = new URL(request.url()).pathname;
      if (path.startsWith('/_next/') && /\.(?:js|css|woff2?)$/.test(path) && request.failure()?.errorText !== 'net::ERR_ABORTED') {
        state.failures.push(`network:${path}`);
      }
    });
    page.on('response', response => {
      const path = new URL(response.url()).pathname;
      if (response.status() >= 400 && (path.startsWith('/api/') || path.startsWith('/_next/'))) {
        state.failures.push(`${response.status()}:${path}`);
      }
    });
    // 조회에도 비용이 생기는 provider 검색 및 모든 domain write를 운영에 보내지 않는다.
    // 개별 UI 계약 시험은 이 guard보다 나중에 등록한 정확한 route에서만 응답을 주입한다.
    await page.route('**/api/v1/**', async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (/\/place-search(?:\/|$)/.test(path) || path === '/api/v1/categories/match') {
        state.providers.push(`${request.method()}:${path}`);
        if (path === '/api/v1/categories/match') await route.fulfill({ json: { match: null } });
        else if (path.endsWith('/opinion')) await route.fulfill({ json: { gemini: null, error: null } });
        else await route.fulfill({ json: { query: '', searched_at: new Date().toISOString(), google: [], kakao: [], naver: [], gemini: null, errors: {} } });
      } else if (!['GET', 'HEAD'].includes(request.method()) || path === '/api/v1/destinations/export') {
        state.blocked.push(`${request.method()}:${path}`);
        state.allowed.add(`503:${path}`);
        await route.fulfill({ status: 503, json: { detail: '테스트에서 운영 전송을 차단했습니다.' } });
      } else await route.fallback();
    });
    info.annotations.push({ type: 'layer', description: 'live-read' });
    await use(state);
    if (state.providers.length) info.annotations.push({ type: 'layer', description: 'browser-provider-fixture' });
    await info.attach('ui-observations', { body: JSON.stringify({ blocked: state.blocked, errors: state.errors, failures: state.failures, browserProviderMocks: state.providers }), contentType: 'application/json' });
    expect(state.blocked, '예상하지 않은 provider/domain write 요청').toEqual([]);
    expect(state.errors, '브라우저 런타임 오류').toEqual([]);
    expect(state.failures.filter(failure => !state.allowed.has(failure)), '예상하지 않은 API/asset 실패').toEqual([]);
  }, { auto: true }],
});
test.skip(process.env.KTC_LIVE_E2E !== '1', '공개 live UI와 비공개 관리자 자격이 필요합니다.');
test.setTimeout(75_000);
export { expect };
export function fault(info: TestInfo) { info.annotations.push({ type: 'layer', description: 'browser-fault' }); }
export function allowed(state: Observations, path: string, ...statuses: number[]) { statuses.forEach(status => state.allowed.add(`${status}:${path}`)); }
export async function login(page: Page, path = '/dagster') {
  await page.goto(`/login?next=${encodeURIComponent(path)}`, { waitUntil: 'domcontentloaded' });
  await page.getByLabel('아이디', { exact: true }).fill(process.env.E2E_ADMIN_USERNAME!);
  await page.getByLabel('비밀번호', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD!);
  const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/auth/login');
  await page.getByRole('button', { name: '로그인', exact: true }).click({ noWaitAfter: true });
  expect((await response).status()).toBe(200);
  await expect.poll(() => new URL(page.url()).pathname).toBe(new URL(path, 'https://local.invalid').pathname);
  await expect(page.locator('#main-content')).toBeVisible();
}
export async function choose(page: Page, label: string, option: string) {
  await page.getByLabel(label, { exact: true }).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}
export async function noOverflow(page: Page) {
  try { await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1); }
  catch (error) {
    const overflow = await page.evaluate(() => Array.from(document.querySelectorAll('*')).filter(node => {
      const rect = node.getBoundingClientRect();
      if (rect.right <= innerWidth + 1 || !rect.width) return false;
      for (let parent = node.parentElement; parent && !['HTML', 'BODY'].includes(parent.tagName); parent = parent.parentElement) {
        if (['hidden', 'auto', 'scroll', 'clip'].includes(getComputedStyle(parent).overflowX)) return false;
      }
      return true;
    }).slice(0, 30).map(node => ({ tag: node.tagName, className: node.className, width: node.getBoundingClientRect().width, right: node.getBoundingClientRect().right })));
    await test.info().attach('document-overflow', { body: JSON.stringify(overflow), contentType: 'application/json' });
    throw error;
  }
}

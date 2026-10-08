import { test, expect, login, fault, allowed, noOverflow } from './live-ui-fixtures';

for (const path of ['/dagster', '/review', '/settings', '/jobs/987654321']) {
  test(`인증 없는 딥링크를 로그인으로 보내고 목적지를 보존한다 ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login\?next=/);
    expect(new URL(page.url()).searchParams.get('next')).toBe(path);
    await expect(page.getByTestId('concierge-common-login')).toBeVisible();
    expect((await page.request.get('/api/v1/admin/dagster/summary')).status()).toBe(401);
  });
}
test('빈 자격은 HTML 검증으로 요청을 보내지 않고 키보드로 입력할 수 있다', async ({ page }) => {
  let submissions = 0; page.on('request', r => { if (new URL(r.url()).pathname === '/api/auth/login') submissions++; });
  await page.goto('/login');
  await page.getByLabel('아이디', { exact: true }).fill('');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  expect(submissions).toBe(0);
  await expect(page.getByLabel('아이디', { exact: true })).toBeFocused();
  await page.keyboard.type(process.env.E2E_ADMIN_USERNAME!); await page.keyboard.press('Tab');
  await expect(page.getByLabel('비밀번호', { exact: true })).toBeFocused();
  await expect(page.getByLabel('비밀번호', { exact: true })).toHaveAttribute('type', 'password');
});
test('잘못된 비밀번호 오류를 알리고 입력 수정 후 정상 로그인한다', async ({ page, observations }) => {
  allowed(observations, '/api/auth/login', 401);
  await page.goto('/login?next=%2Fjobs%3Fattention%3Dopen');
  await page.getByLabel('아이디', { exact: true }).fill(process.env.E2E_ADMIN_USERNAME!);
  await page.getByLabel('비밀번호', { exact: true }).fill('invalid-e2e-password');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page.locator('[data-slot=login-error]')).toContainText('아이디 또는 비밀번호');
  await page.getByLabel('비밀번호', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD!);
  await expect(page.locator('[data-slot=login-error]')).toHaveText('');
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  await expect(page).toHaveURL(/\/jobs\?attention=open$/);
  await expect(page.getByRole('button', { name: '확인 필요만', exact: true })).toHaveAttribute('aria-pressed', 'true');
});
for (const [code, status, message] of [
  ['RATE_LIMITED', 429, '잠시 제한'], ['AUTH_MISCONFIGURED', 503, '준비되지'],
  ['INVALID_ORIGIN', 403, '요청 출처'], ['UNKNOWN', 500, '로그인하지 못했습니다.'],
] as const) {
  test(`로그인 오류 종류를 안내하고 다시 제출해 복구한다 ${code}`, async ({ page, observations }, info) => {
    fault(info); allowed(observations, '/api/auth/login', status);
    await page.route('**/api/auth/login', r => r.fulfill({ status, json: { error: code } }));
    await page.goto('/login?next=%2Fsettings');
    await page.getByLabel('아이디', { exact: true }).fill(process.env.E2E_ADMIN_USERNAME!);
    await page.getByLabel('비밀번호', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD!);
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await expect(page.locator('[data-slot=login-error]')).toContainText(message);
    await page.unroute('**/api/auth/login');
    await page.getByLabel('비밀번호', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD!);
    const restored = page.waitForResponse(r => new URL(r.url()).pathname === '/api/auth/login');
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    expect((await restored).status()).toBe(200);
    await expect(page).toHaveURL(/\/settings$/);
  });
}
test('로그인 네트워크 실패와 중복 제출을 처리한다', async ({ page }, info) => {
  fault(info); let count = 0;
  await page.route('**/api/auth/login', async r => { count++; await new Promise(resolve => setTimeout(resolve, 700)); await r.abort(); });
  await page.goto('/login');
  await page.getByLabel('비밀번호', { exact: true }).fill('test-only');
  const submit = page.getByRole('button', { name: '로그인', exact: true });
  await submit.click();
  await expect(page.getByTestId('concierge-common-login')).toHaveAttribute('aria-busy', 'true');
  await page.locator('[data-slot=login-submit]').dispatchEvent('click');
  await expect(page.locator('[data-slot=login-error]')).toContainText('네트워크 오류'); expect(count).toBe(1);
});
for (const next of ['https://example.invalid/attack', '//example.invalid/attack', 'javascript:alert(1)']) {
  test(`로그인 뒤 외부 목적지로 이동하지 않는다 ${next.split(':')[0]}`, async ({ page }) => {
    await page.goto(`/login?next=${encodeURIComponent(next)}`);
    await page.getByLabel('아이디', { exact: true }).fill(process.env.E2E_ADMIN_USERNAME!);
    await page.getByLabel('비밀번호', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD!);
    await page.getByRole('button', { name: '로그인', exact: true }).click();
    await expect.poll(() => new URL(page.url()).pathname).toBe('/');
    await expect(page.locator('#main-content')).toBeVisible();
  });
}
test('로그아웃 UI와 새 탭에서 폐기된 세션을 확인한다', async ({ page, context }) => {
  await login(page, '/settings');
  const other = await context.newPage(); await other.goto('/jobs');
  await expect(other.locator('#main-content')).toBeVisible();
  await page.getByRole('button', { name: '로그아웃', exact: true }).filter({ visible: true }).click();
  await expect(page).toHaveURL(/\/login/);
  expect((await other.request.get('/api/v1/admin/dagster/summary')).status()).toBe(401);
  await other.reload(); await expect(other).toHaveURL(/\/login\?next=/);
  await other.close();
});
test('본문 건너뛰기와 사이드바 접기 상태가 새로고침 뒤 유지된다', async ({ page }) => {
  await login(page, '/jobs');
  const skip = page.getByRole('link', { name: '본문으로 건너뛰기', exact: true });
  await skip.focus(); await page.keyboard.press('Enter'); await expect(page.locator('#main-content')).toBeFocused();
  await page.getByRole('button', { name: '좌측 메뉴 접기', exact: true }).click();
  await page.reload(); await expect(page.getByRole('button', { name: '좌측 메뉴 펼치기', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '좌측 메뉴 펼치기', exact: true }).click();
  await page.reload(); await expect(page.getByRole('button', { name: '좌측 메뉴 접기', exact: true })).toBeVisible();
});
const pages = [
  ['/', '결과'], ['/collect', '수집'], ['/jobs', '작업'], ['/review', '검수'],
  ['/settings', '설정'], ['/status', '상태'], ['/dagster', 'Dagster'], ['/api-test', 'API 테스트'],
] as const;
for (const width of [320, 390, 768, 1440]) {
  test(`전체 메뉴의 반응형 UI와 현재 경로를 확인한다 ${width}`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: width < 500 ? 844 : 1000 });
    await login(page, '/jobs');
    for (const [path, name] of pages) await test.step(name, async () => {
      const primary: Record<string, string> = { '/': '/api/v1/destinations', '/collect': '/api/v1/source-targets', '/jobs': '/api/v1/runs', '/review': '/api/v1/destinations/unmatched', '/settings': '/api/v1/settings', '/status': '/api/v1/metrics', '/dagster': '/api/v1/admin/dagster/summary', '/api-test': '/api/v1/themes' };
      const response = page.waitForResponse(r => new URL(r.url()).pathname === primary[path]);
      await page.goto(path, { waitUntil: 'domcontentloaded' });
      expect((await response).status()).toBe(200);
      await expect(page.locator('#main-content')).toBeVisible();
      await expect(page.locator(`a[href="${path}"][aria-current="page"]:visible`).first()).toBeInViewport();
      await noOverflow(page);
    });
    await page.screenshot({ path: info.outputPath(`menu-${width}.png`), fullPage: true });
  });
}

test('모바일 메뉴를 가로 스크롤해 링크를 활성화하고 현재 항목으로 이동한다', async({page})=>{
  await page.setViewportSize({width:390,height:844});await login(page,'/jobs');
  const link=page.getByTestId('concierge-common-menu').getByRole('link',{name:'API 테스트',exact:true});
  await link.scrollIntoViewIfNeeded();await link.focus();await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/api-test$/);await expect(link).toHaveAttribute('aria-current','page');await expect(link).toBeInViewport();
});

import { test, expect, type Page } from '@playwright/test';

test.skip(process.env.KTC_LIVE_E2E !== '1', 'live UI와 비공개 관리자 자격이 필요합니다.');
// 15초 준비 상한과 수동 재시도 뒤 실제 타일 응답 예산을 함께 확보한다.
test.setTimeout(75_000);

async function login(page: Page) {
  await page.goto('/login?next=%2F', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('아이디', { exact: true }).fill(process.env.E2E_ADMIN_USERNAME!);
  await page.getByLabel('비밀번호', { exact: true }).fill(process.env.E2E_ADMIN_PASSWORD!);
  await page.getByRole('button', { name: '로그인', exact: true }).click({ noWaitAfter: true });
  await expect(page.locator('#vworld-map-container')).toBeVisible();
}

async function ready(page: Page) {
  const map = page.locator('#vworld-map-container');
  await expect(map.locator('canvas')).toBeVisible();
  // canvas 생성만으로 준비 완료로 오인하지 않는다. 실제 load 뒤 마커가 마운트된다.
  await expect.poll(() => map.locator('.maplibregl-marker').count(), { timeout: 30_000 }).toBeGreaterThan(0);
  await expect(map.getByText('지도 로딩 중', { exact: true })).toHaveCount(0);
  await expect(map.getByRole('button', { name: '지도 다시 시도' })).toHaveCount(0);
}

async function selectPlace(page: Page) {
  const rows = page.getByRole('region', { name: '장소 목록', exact: true }).locator('div[data-selected]');
  await expect.poll(() => rows.count()).toBeGreaterThan(1);
  const row = rows.nth(1);
  await row.locator('button').first().click();
  await expect(row).toHaveAttribute('data-selected', 'true');
  const number = await row.locator('[data-marker-number]').getAttribute('data-marker-number');
  expect(number).toBeTruthy();
  return { rows, count: await rows.count(), number };
}

function nextTile(page: Page) {
  return page.waitForResponse(response =>
    new URL(response.url()).hostname === 'api.vworld.kr' &&
    response.status() === 200 && response.headers()['content-type']?.startsWith('image/png') === true,
    { timeout: 30_000 },
  );
}

async function preserved(page: Page, selection: Awaited<ReturnType<typeof selectPlace>>) {
  expect(await selection.rows.count()).toBe(selection.count);
  await expect(selection.rows.nth(1)).toHaveAttribute('data-selected', 'true');
  await expect(page.locator(`#vworld-map-container [data-selected="true"][data-interaction-id="${selection.number}"]`)).toBeVisible();
}

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`실제 지도 타일과 장소 마커 준비 ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const tiles: number[] = [];
    page.on('response', response => {
      if (new URL(response.url()).hostname === 'api.vworld.kr' && response.headers()['content-type']?.startsWith('image/')) {
        tiles.push(response.status());
      }
    });
    await login(page);
    await ready(page);
    expect(tiles.some(status => status === 200)).toBe(true);
  });
}

test('응답 없는 지도는 지연을 알리고 수동 재시도로 복구한다', async ({ page }) => {
  let block = true;
  let blockedRequests = 0;
  const pending: import('@playwright/test').Route[] = [];
  await page.route('https://api.vworld.kr/**', route => {
    if (block) { blockedRequests += 1; pending.push(route); }
    else void route.continue();
  });
  await login(page);
  const map = page.locator('#vworld-map-container');
  await expect(map.getByText('지도 로딩 중', { exact: true })).toBeVisible();
  await expect(map.getByRole('status')).toContainText('지도 응답이 지연되고 있습니다.', { timeout: 25_000 });
  const count = blockedRequests;
  await page.waitForTimeout(2_000);
  expect(blockedRequests).toBe(count); // 네트워크 장애 중 자동 요청 루프를 만들지 않는다.
  const selection = await selectPlace(page);
  block = false;
  const tile = nextTile(page);
  await map.getByRole('button', { name: '지도 다시 시도', exact: true }).click();
  await Promise.allSettled(pending.map(route => route.abort()));
  await tile;
  await ready(page);
  await preserved(page, selection);
});

test('WebGL 초기화 실패를 표시하고 지도만 다시 초기화한다', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.name));
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    (window as Window & { blockMapWebGL?: boolean }).blockMapWebGL = true;
    HTMLCanvasElement.prototype.getContext = function (...args: Parameters<typeof original>) {
      if ((window as Window & { blockMapWebGL?: boolean }).blockMapWebGL && String(args[0]).startsWith('webgl')) return null;
      return original.apply(this, args);
    } as typeof original;
  });
  await login(page);
  const map = page.locator('#vworld-map-container');
  await expect(map.getByRole('alert')).toContainText('브라우저의 그래픽 가속 설정');
  await expect(map.locator('canvas')).toHaveCount(0); // 미완성 Map을 생성하지 않는다.
  const selection = await selectPlace(page);
  await page.evaluate(() => { (window as Window & { blockMapWebGL?: boolean }).blockMapWebGL = false; });
  const tile = nextTile(page);
  await map.getByRole('button', { name: '지도 다시 시도', exact: true }).click();
  await tile;
  await ready(page);
  await preserved(page, selection);
  expect(errors).toEqual([]);
});

for (const mode of ["missing-extension", "unconfirmed-loss"] as const) {
  test(`GPU 검사 자원 해제를 확인할 수 없으면 추가 지도를 생성하지 않는다 ${mode}`, async ({ page }) => {
    await page.addInitScript((mode) => {
      const original = HTMLCanvasElement.prototype.getContext;
      (window as Window & { mapProbeCount?: number }).mapProbeCount = 0;
      HTMLCanvasElement.prototype.getContext = function (...args: Parameters<typeof original>) {
        const context = original.apply(this, args);
        if (String(args[0]) === 'webgl2' && context) {
          const state = window as Window & { mapProbeCount?: number };
          state.mapProbeCount = (state.mapProbeCount ?? 0) + 1;
          const gl = context as WebGL2RenderingContext;
          const getExtension = gl.getExtension.bind(gl);
          gl.getExtension = ((name: string) => name === 'WEBGL_lose_context'
            ? mode === 'missing-extension' ? null : { loseContext() {}, restoreContext() {} }
            : getExtension(name)) as typeof gl.getExtension;
        }
        return context;
      } as typeof original;
    }, mode);
    await login(page);
    const map = page.locator('#vworld-map-container');
    await expect(map.getByRole('alert')).toContainText('지도를 안전하게 초기화하지 못했습니다.');
    await expect(map.locator('canvas')).toHaveCount(0);
    await expect(map.getByRole('button', { name: '지도 다시 시도' })).toHaveCount(0);
    const before = await page.evaluate(() => (window as Window & { mapProbeCount?: number }).mapProbeCount);
    expect(before).toBe(1);
    await selectPlace(page); // 부모 rerender에도 검사 context를 추가 생성하지 않는다.
    await page.waitForTimeout(2_000);
    expect(await page.evaluate(() => (window as Window & { mapProbeCount?: number }).mapProbeCount)).toBe(before);
    await expect(map.getByText('지도 로딩 중', { exact: true })).toHaveCount(0);
  });
}

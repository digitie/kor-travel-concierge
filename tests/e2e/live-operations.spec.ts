import { test, expect, login, fault, allowed, choose } from './live-ui-fixtures';
import type { Page } from '@playwright/test';
const summary = '/api/v1/admin/dagster/summary';
const panel = (page: Page) => page.getByTestId('concierge-common-dagster');
async function native(page: Page) {
  const response = page.waitForResponse(r => new URL(r.url()).pathname === summary);
  await login(page, '/dagster'); const body = await (await response).json();
  expect(body.status).toBe('ok'); expect(body.snapshot.repositories).toHaveLength(1);
  expect(body.snapshot.repositories[0].locationName).toBe('ktc.dagster.definitions');
  await expect(page.getByLabel('실행 검색', { exact: true })).toBeVisible();
  expect(body.snapshot.runs.length).toBeGreaterThan(0);
  return body;
}
async function selected(page: Page, id: string) {
  await page.getByLabel('실행 검색', { exact: true }).fill(id);
  await panel(page).getByRole('button', { name: new RegExp(`실행 상세: .*${id}`) }).click();
  await expect(page.getByTestId('concierge-selected-run')).toContainText(id);
}
test('실제 native 실행 검색·선택·선택 해제와 코드 위치를 확인한다', async ({ page }) => {
  const body = await native(page); const run = body.snapshot.runs[0];
  await selected(page, run.runId);
  await expect(page.getByTestId('concierge-selected-run')).toContainText(run.status);
  await expect(page.getByTestId('concierge-selected-run').getByRole('link', { name: 'Dagster 실행 로그' })).toHaveAttribute('href', new RegExp(`/runs/${run.runId}$`));
  await panel(page).getByRole('button', { name: new RegExp(`실행 상세: .*${run.runId}`) }).click();
  await expect(page.getByTestId('concierge-selected-run')).toHaveCount(0);
  await page.getByLabel('실행 검색', { exact: true }).fill('e2e-no-such-native-run');
  await expect(panel(page).getByText('검색 조건에 맞는 실행이 없습니다.')).toBeVisible();
  await page.getByLabel('실행 검색', { exact: true }).fill('');
  await expect(panel(page).getByRole('button', { name: /실행 상세:/ }).first()).toBeVisible();
});
for (const mode of ['degraded', 'http500', 'invalid-json', 'timeout'] as const) {
  test(`Dagster 첫 조회 오류와 수동 복구 ${mode}`, async ({ page, observations }, info) => {
    fault(info); allowed(observations, summary, 500); const pending: import('@playwright/test').Route[] = [];
    await page.route(`**${summary}`, async route => {
      if (mode === 'timeout') { pending.push(route); return; }
      await route.fulfill(mode === 'degraded' ? { json: { status: 'degraded', snapshot: null } }
        : mode === 'http500' ? { status: 500, json: { detail: 'E2E 장애' } }
        : { status: 200, contentType: 'application/json', body: '{invalid' });
    });
    await login(page, '/dagster');
    await expect(panel(page).getByRole('alert')).toContainText('Dagster 상태를 확인하지 못했습니다.', { timeout: 22_000 });
    await expect(page.getByLabel('실행 검색', { exact: true })).toHaveCount(0);
    await expect(page.getByTestId('concierge-selected-run')).toHaveCount(0);
    await page.unroute(`**${summary}`); await Promise.allSettled(pending.map(r => r.abort()));
    const response = page.waitForResponse(r => new URL(r.url()).pathname === summary && r.status() === 200);
    await panel(page).getByRole('button', { name: '다시 시도', exact: true }).click();
    expect((await (await response).json()).status).toBe('ok');
    await expect(panel(page).getByRole('alert')).toHaveCount(0);
    await expect(page.getByLabel('실행 검색', { exact: true })).toBeVisible();
  });
}
for (const status of [401, 403, 503]) {
  test(`정상 조회 뒤 ${status}의 민감 데이터 수명을 확인한다`, async ({ page, observations }, info) => {
    fault(info); allowed(observations, summary, status);
    const body = await native(page); const id = body.snapshot.runs[0].runId; await selected(page, id);
    await page.route(`**${summary}`, r => r.fulfill({ status, json: {} }));
    await panel(page).getByRole('button', { name: '새로고침', exact: true }).click();
    await expect(panel(page).getByRole('alert')).toBeVisible();
    if (status === 503) await expect(page.getByTestId('concierge-selected-run')).toContainText(id);
    else {
      await expect(page.getByTestId('concierge-selected-run')).toHaveCount(0);
      await expect(page.getByLabel('실행 검색', { exact: true })).toHaveCount(0);
    }
    await page.unroute(`**${summary}`);
    await panel(page).getByRole('button', { name: '다시 시도', exact: true }).click();
    await expect(panel(page).getByRole('alert')).toHaveCount(0);
    if (status !== 503) await expect(page.getByTestId('concierge-selected-run')).toHaveCount(0);
  });
}
for (const mode of ['publicUrl', 'runs']) {
  test(`손상된 200 응답은 마지막 정상 Dagster 상태를 덮지 않는다 ${mode}`, async ({ page }, info) => {
    fault(info); const actual = await native(page); const id = actual.snapshot.runs[0].runId; await selected(page, id);
    const malformed = structuredClone(actual);
    if (mode === 'publicUrl') { malformed.publicUrl = null; malformed.snapshot.runs = []; } else delete malformed.snapshot.runs;
    await page.route(`**${summary}`, r => r.fulfill({ json: malformed }));
    await panel(page).getByRole('button', { name: '새로고침', exact: true }).click();
    await expect(panel(page).getByRole('alert')).toBeVisible();
    await expect(page.getByTestId('concierge-selected-run')).toContainText(id);
    await page.unroute(`**${summary}`);
    await panel(page).getByRole('button', { name: '다시 시도', exact: true }).click();
    await expect(panel(page).getByRole('alert')).toHaveCount(0);
  });
}
test('다음 snapshot에 없는 실행의 선택과 도메인 링크를 제거한다', async ({ page }, info) => {
  fault(info); const body = await native(page); const run = body.snapshot.runs[0]; await selected(page, run.runId);
  const next = structuredClone(body); next.snapshot.runs = next.snapshot.runs.filter((r: {runId: string}) => r.runId !== run.runId);
  await page.route(`**${summary}`, r => r.fulfill({ json: next }));
  await panel(page).getByRole('button', { name: '새로고침', exact: true }).click();
  await expect(page.getByTestId('concierge-selected-run')).toHaveCount(0);
});
test('maintenance 실행의 domain 링크와 runtime 미확인 표시를 구분한다', async ({ page }, info) => {
  fault(info); const body = await native(page); const next = structuredClone(body); const run = next.snapshot.runs[0];
  run.domainRunId = null; run.maxRuntimeSeconds = null;
  await page.route(`**${summary}`, r => r.fulfill({ json: next }));
  await panel(page).getByRole('button', { name: '새로고침', exact: true }).click(); await selected(page, run.runId);
  await expect(page.getByTestId('concierge-selected-run')).toContainText('시간 상한: 미확인');
  await expect(page.getByTestId('concierge-selected-run').getByRole('link', { name: /수집 작업/ })).toHaveCount(0);
});
test('화면 이탈 때 Dagster 요청 signal을 취소하고 선택 영역을 제거한다', async ({ page }, info) => {
  fault(info);
  await page.addInitScript(() => {
    const original = window.fetch;
    (window as typeof window & { dagsterSignals: { id: number; reason: string | null }[] }).dagsterSignals = [];
    window.fetch = function(input, init) {
      if (String(input).includes('/api/v1/admin/dagster/summary') && init?.signal) {
        const signals = (window as typeof window & { dagsterSignals: { id: number; reason: string | null }[] }).dagsterSignals;
        const record = { id: signals.length, reason: null as string | null }; signals.push(record);
        const signal = init.signal;
        signal.addEventListener('abort', () => { record.reason = signal.reason?.name ?? 'unknown'; }, { once: true });
      }
      return original.call(this, input, init);
    };
  });
  await native(page); let pending: import('@playwright/test').Route | undefined;
  await page.route(`**${summary}`, r => { pending = r; });
  await panel(page).getByRole('button', { name: '새로고침', exact: true }).click();
  await expect.poll(() => !!pending).toBe(true);
  const held = await page.evaluate(() => (window as typeof window & { dagsterSignals: { id: number; reason: string | null }[] }).dagsterSignals.at(-1)!);
  expect(held.reason).toBeNull();
  try {
    await page.getByRole('link', { name: '작업', exact: true }).click();
    // 특정 보류 요청의 cleanup AbortError를 2초 안에 관측한다.
    // 완료된 다른 요청이나 15초 TimeoutError는 이 계약을 통과시킬 수 없다.
    await expect.poll(() => page.evaluate(id => (window as typeof window & { dagsterSignals: { id: number; reason: string | null }[] }).dagsterSignals.find(s => s.id === id)?.reason, held.id), { timeout: 2000 }).toBe('AbortError');
    await expect(page.getByRole('heading', { name: '작업', exact: true })).toBeVisible();
    await expect(panel(page)).toHaveCount(0); await expect(page.getByTestId('concierge-selected-run')).toHaveCount(0);
  } finally { await pending?.abort().catch(() => undefined); }
});
test('작업 상태·attention 필터는 실제 요청과 URL을 갱신한다', async ({ page }) => {
  await login(page, '/jobs');
  for (const [name, value] of [['실패', 'failed'], ['완료', 'done'], ['취소', 'cancelled']] as const) {
    const response = page.waitForResponse(r => { const u = new URL(r.url()); return u.pathname === '/api/v1/runs' && u.searchParams.get('state') === value; });
    await choose(page, '작업 상태 필터', name); const actual = await response;
    expect(actual.status()).toBe(200); const u = new URL(actual.url());
    expect(u.searchParams.get('terminal')).toBe('true'); expect(u.searchParams.get('user_jobs_only')).toBe('true'); expect(u.searchParams.has('cursor')).toBe(false);
  }
  const attention = page.waitForResponse(r => { const u = new URL(r.url()); return u.pathname === '/api/v1/runs' && u.searchParams.get('attention') === 'open'; });
  await page.getByRole('button', { name: '확인 필요만', exact: true }).click(); expect((await attention).status()).toBe(200);
  await expect(page).toHaveURL(/attention=open/); await page.reload();
  await expect(page.getByRole('button', { name: '확인 필요만', exact: true })).toHaveAttribute('aria-pressed', 'true');
});
for (const path of ['/api/v1/runs/queue', '/api/v1/runs']) {
  test(`작업의 일부 조회 실패는 다른 영역을 보존한다 ${path.split('/').pop()}`, async ({ page, observations }, info) => {
    fault(info); allowed(observations, path, 503);
    await page.route(`**${path}${path.endsWith('/queue') ? '' : '?*'}`, r => r.fulfill({ status: 503, json: { detail: 'E2E 부분 오류' } }));
    const otherPath = path.endsWith('/queue') ? '/api/v1/runs' : '/api/v1/runs/queue';
    const otherResponse = page.waitForResponse(r => new URL(r.url()).pathname === otherPath);
    await login(page, '/jobs');
    const response = await otherResponse; expect(response.status()).toBe(200); const body = await response.json();
    const otherPanel = page.locator('section').filter({ has: page.getByRole('heading', { name: path.endsWith('/queue') ? '작업 이력' : '진행 중 · 대기', exact: true }) });
    if (body.items.length) {
      await expect(otherPanel.locator('tbody tr')).toHaveCount(body.items.length);
      await expect(otherPanel.locator('tbody tr').first()).toContainText(String(body.items[0].job_id));
    } else await expect(otherPanel.getByText(path.endsWith('/queue') ? '완료된 작업 이력이 없습니다.' : '실행 중이거나 대기 중인 작업이 없습니다.', { exact: true })).toBeVisible();
    await expect(otherPanel.getByRole('alert')).toHaveCount(0);
    await expect(page.locator('#main-content').getByRole('alert').filter({ hasText: path.endsWith('/queue') ? '작업 대기열' : '작업 이력' })).toBeVisible({ timeout: 20_000 });
    const other = path.endsWith('/queue') ? '작업 이력' : '진행 중 · 대기';
    await expect(page.getByRole('heading', { name: other, exact: true })).toBeVisible();
    await page.unroute(`**${path}${path.endsWith('/queue') ? '' : '?*'}`);
    const restoredResponse = page.waitForResponse(r => new URL(r.url()).pathname === path && r.status() === 200);
    await page.getByRole('button', { name: '다시 시도', exact: true }).click();
    const restored = await(await restoredResponse).json();
    const recoveredPanel = page.locator('section').filter({ has: page.getByRole('heading', { name: path.endsWith('/queue') ? '진행 중 · 대기' : '작업 이력', exact: true }) });
    if (restored.items.length) await expect(recoveredPanel.locator('tbody tr')).toHaveCount(restored.items.length);
    else await expect(recoveredPanel.getByText(path.endsWith('/queue') ? '실행 중이거나 대기 중인 작업이 없습니다.' : '완료된 작업 이력이 없습니다.', { exact: true })).toBeVisible();
    await expect(page.locator('#main-content').getByRole('alert')).toHaveCount(0);
  });
}
test('작업 상세의 없는 ID는 오류를 빈 성공으로 표시하지 않는다', async ({ page, observations }) => {
  const id = '987654321'; allowed(observations, `/api/v1/runs/${id}`, 404); allowed(observations, `/api/v1/runs/${id}/video-stats`, 404);
  await login(page, `/jobs/${id}`);
  await expect(page.getByRole('alert').filter({ hasText: '작업' })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('button', { name: '다시 시도', exact: true }).first()).toBeVisible();
});
test('상태 metrics 오류를 다른 운영 정보와 구분하고 복구한다', async ({ page, observations }, info) => {
  fault(info); allowed(observations, '/api/v1/metrics', 503);
  await page.route('**/api/v1/metrics', r => r.fulfill({ status: 503, json: { detail: 'E2E metrics 오류' } }));
  const independent = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/admin/login-events');
  await login(page, '/status');
  await expect(page.getByLabel('상태 정보 불러오기 오류')).toBeVisible({ timeout: 20_000 });
  const independentResponse = await independent; expect(independentResponse.status()).toBe(200);
  const events = await independentResponse.json(); const records = Array.isArray(events) ? events : events.items;
  expect(records.length).toBeGreaterThan(0);
  const security = page.locator('section').filter({ has: page.getByRole('heading', { name: '로그인 기록', exact: true }) }).last();
  await expect(security.getByText(records[0].attempted_username, { exact: false }).first()).toBeVisible();
  await expect(security.getByRole('alert')).toHaveCount(0);
  await page.unroute('**/api/v1/metrics');
  const restored = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/metrics' && r.status() === 200);
  await page.getByRole('button', { name: '새로고침', exact: true }).click();
  const metrics = await(await restored).json();
  expect(metrics.database.travel_places).toBeGreaterThan(0); expect(metrics.database.youtube_videos).toBeGreaterThan(0);
  await expect(page.getByLabel('운영 요약 지표')).toContainText(`${metrics.database.travel_places.toLocaleString()} 장소 · ${metrics.database.youtube_videos.toLocaleString()} 영상`);
  await expect(page.getByLabel('상태 정보 불러오기 오류')).toHaveCount(0);
});

test('실제 작업 유형 옵션은 정확한 job_types 요청과 cursor 초기화를 적용한다',async({page})=>{
  const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/runs/queue');await login(page,'/jobs');
  const body=await(await response).json();expect(body.user_job_types.length).toBeGreaterThan(0);
  await page.getByLabel('작업 유형 필터').click();const option=page.getByRole('option').nth(1);await expect(option).toBeVisible();
  const filtered=page.waitForResponse(r=>{const u=new URL(r.url());return u.pathname==='/api/v1/runs'&&u.searchParams.get('job_types')===body.user_job_types[0]});
  await option.click();const result=await filtered;expect(result.status()).toBe(200);const url=new URL(result.url());expect(url.searchParams.has('cursor')).toBe(false);expect(url.searchParams.has('user_jobs_only')).toBe(false);
});

import { test, expect, login, fault, allowed, choose } from './live-ui-fixtures';
import type { Page } from '@playwright/test';
test('수집 입력이 비어 있으면 등록 없이 필드 오류를 표시한다', async ({ page }) => {
  await login(page, '/collect'); await page.getByRole('button', { name: '수집 시작', exact: true }).click();
  await expect(page.getByText('수집 대상을 입력하세요.', { exact: true })).toBeVisible();
  await expect(page.locator('#harvest-target')).toHaveAttribute('aria-invalid', 'true');
});
for (const [value, kind] of [
  ['부산 여행', '검색어'], ['https://youtu.be/dQw4w9WgXcQ', '영상'],
  ['https://www.youtube.com/playlist?list=PL12345678901234567890', '재생목록'],
  ['https://www.youtube.com/@travel-example', '유튜버'],
] as const) {
  test(`수집 자동 판별은 외부 호출 없이 입력 유형을 표시한다 ${kind}`, async ({ page }) => {
    await login(page, '/collect'); await page.locator('#harvest-target').fill(value);
    await expect(page.getByText('자동 인식:', { exact: false })).toContainText(kind);
  });
}
for (const value of ['0', '301', '1.5']) {
  test(`수집 최대 영상 수 경계를 검증한다 ${value}`, async ({ page }) => {
    await login(page, '/collect'); await page.locator('#harvest-target').fill('E2E 미전송 검색어');
    await page.locator('#harvest-max-videos').fill(value); await page.getByRole('button', { name: '수집 시작', exact: true }).click();
    // min/max/step의 native validation 또는 Zod 모두 제출 전에 차단해야 한다.
    const invalid = await page.locator('#harvest-max-videos').evaluate((node: HTMLInputElement) => !node.validity.valid || node.getAttribute('aria-invalid') === 'true');
    expect(invalid).toBe(true);
  });
}
test('반복·콘텐츠·강제 다운로드 폼을 변경하고 실제 등록 없이 되돌린다', async ({ page }) => {
  await login(page, '/collect'); await page.getByRole('checkbox', { name: '반복 검색 도움말', exact: true }).check();
  await choose(page, '반복 간격', '1주일'); await page.locator('#harvest-repeat-count').fill('3');
  await choose(page, '콘텐츠 유형', '숏츠만'); await page.getByRole('checkbox', { name: '강제 다운로드(전체 재수집) 도움말', exact: true }).check();
  await expect(page.locator('#harvest-repeat-count')).toHaveValue('3');
  await expect(page.locator('#harvest-content-filter')).toContainText('숏츠만');
  await page.getByRole('checkbox', { name: '반복 검색 도움말', exact: true }).uncheck(); await expect(page.locator('#harvest-repeat-count')).toHaveCount(0);
});
test('설정 키는 빈 password 입력이고 프롬프트 4000자 경계를 표시한다', async ({ page }) => {
  await login(page, '/settings'); const inputs = page.locator('input[id^="settings-"]');
  expect(await inputs.count()).toBe(9);
  for (const input of await inputs.all()) { await expect(input).toHaveValue(''); await expect(input).toHaveAttribute('type', 'password'); }
  const prompt = page.getByLabel('AI 사전 프롬프트', { exact: true }); await prompt.fill('가'.repeat(4001));
  await expect(prompt).toHaveAttribute('aria-invalid', 'true'); await expect(page.locator('#settings-save-button')).toBeDisabled();
  await prompt.fill('가'.repeat(4000)); await expect(prompt).toHaveAttribute('aria-invalid', 'false'); await expect(page.locator('#settings-save-button')).toBeEnabled();
});
test('설정 저장 오류는 입력을 보존하고 성공 표시를 만들지 않는다', async ({ page, observations }, info) => {
  fault(info); allowed(observations, '/api/v1/settings', 503); let submitted: Record<string, unknown> | undefined;
  await page.route('**/api/v1/settings', async r => {
    if (r.request().method() !== 'POST') return r.fallback();
    submitted = r.request().postDataJSON(); await r.fulfill({ status: 503, json: { detail: 'E2E 설정 저장 오류' } });
  });
  await login(page, '/settings'); await page.getByLabel('AI 사전 프롬프트', { exact: true }).fill('E2E 브라우저 한정 프롬프트');
  await page.locator('#settings-save-button').click(); await expect(page.locator('#main-content').getByText('API 요청 실패(503): E2E 설정 저장 오류', { exact: true })).toBeVisible();
  expect(Object.keys(submitted!).sort()).toEqual(['ai_preprompt', 'gemini_engine_version']);
  await expect(page.getByLabel('AI 사전 프롬프트', { exact: true })).toHaveValue('E2E 브라우저 한정 프롬프트');
  await expect(page.getByText('저장했습니다.', { exact: true })).toHaveCount(0);
});
test('설정 키 폐기 확인창을 취소하고 focus를 돌려준다', async ({ page }) => {
  await login(page, '/settings'); const trigger = page.getByRole('button', { name: '폐기', exact: true }).first();
  await expect(trigger).toBeVisible(); await trigger.click(); await expect(page.getByRole('alertdialog')).toBeVisible();
  await page.keyboard.press('Escape'); await expect(page.getByRole('alertdialog')).toHaveCount(0); await expect(trigger).toBeFocused();
});
test('API 테스트 UI는 실제 공급 GET과 응답 상태를 보여준다', async ({ page }) => {
  await login(page, '/api-test'); const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/themes');
  await page.getByRole('button', { name: '실행', exact: true }).click(); expect((await response).status()).toBe(200);
  await expect(page.getByText('HTTP 200', { exact: true })).toBeVisible();
});
test('API 테스트의 HTTP 오류는 로그인 이탈 없이 표시한다', async ({ page, observations }, info) => {
  fault(info); allowed(observations, '/api/v1/themes', 503);
  await login(page, '/api-test'); await page.route('**/api/v1/themes', r => r.fulfill({ status: 503, json: { detail: 'E2E 공급 오류' } }));
  await page.getByRole('button', { name: '실행', exact: true }).click();
  await expect(page.getByText('HTTP 503', { exact: true })).toBeVisible(); await expect(page.getByText(/E2E 공급 오류/)).toBeVisible();
  await expect(page).toHaveURL(/\/api-test$/);
});

const run = (id: string, state: 'failed' | 'running') => ({ job_id: id, job_type: 'harvest', source: 'ui-fixture', target_type: 'keyword', target_id: 'UI fixture', target_label: `E2E ${state}`, state, progress: 0.2, current_message: '브라우저 한정 작업', status_logs: [], retry_count: 0, last_error: state === 'failed' ? 'E2E 실패' : null, restart_of_run_id: null, attention: state === 'failed' ? 'open' : null, result: null, created_at: '2026-10-01T00:00:00Z', started_at: '2026-10-01T00:01:00Z', finished_at: state === 'failed' ? '2026-10-01T00:02:00Z' : null });
async function jobFixture(page: Page) {
  await page.route('**/api/v1/runs/queue', r => r.fulfill({ json: { items: [run('920001', 'running')], running_count: 1, pending_count: 0, open_attention_count: 1, has_more: false, user_job_types: ['harvest'] } }));
  await page.route('**/api/v1/runs?*', r => r.fulfill({ json: { items: [run('920002', 'failed')], total: 1, has_more: false, next_cursor: null, newest_id: 920002, newer_than: null } }));
  await login(page, '/jobs');
  await expect(page.locator('tr').filter({ hasText: 'E2E failed' })).toBeVisible();
}
for (const action of ['중지', '다시 시작', '삭제']) {
  test(`작업 ${action} 확인창 취소는 운영 요청을 보내지 않는다`, async ({ page }, info) => {
    fault(info); await jobFixture(page); const row = page.locator('tr').filter({ hasText: action === '중지' ? 'E2E running' : 'E2E failed' });
    const trigger = row.getByRole('button', { name: action, exact: true }); await trigger.click();
    await expect(page.getByRole('alertdialog')).toBeVisible(); await page.keyboard.press('Escape');
    await expect(page.getByRole('alertdialog')).toHaveCount(0); await expect(trigger).toBeFocused();
  });
}
for (const [action, path, status] of [
  ['중지', '/api/v1/runs/920001/stop', 500], ['다시 시작', '/api/v1/runs/920002/restart', 409], ['삭제', '/api/v1/runs/920002', 409],
] as const) {
  test(`작업 ${action} 실패는 허위 성공을 표시하지 않는다`, async ({ page, observations }, info) => {
    fault(info); allowed(observations, path, status); let attempts = 0;
    await page.route(`**${path}`, async r => { attempts++; await r.fulfill({ status, json: { detail: 'E2E 작업 충돌' } }); });
    await jobFixture(page); const row = page.locator('tr').filter({ hasText: action === '중지' ? 'E2E running' : 'E2E failed' });
    await row.getByRole('button', { name: action, exact: true }).click();
    await page.getByRole('alertdialog').getByRole('button', { name: action, exact: true }).click();
    await expect(page.locator('#main-content').getByRole('alert')).toContainText('E2E 작업 충돌'); expect(attempts).toBe(1);
    await expect(row).toBeVisible(); await expect(page).toHaveURL(/\/jobs$/);
  });
}
test('재시작 등록 중 중복을 막고 기존 재시작 사용을 구분한다', async ({ page }, info) => {
  fault(info); let attempts = 0; let pending: import('@playwright/test').Route | undefined;
  await page.route('**/api/v1/runs/920002/restart', r => { attempts++; pending = r; });
  await jobFixture(page); const row = page.locator('tr').filter({ hasText: 'E2E failed' });
  await row.getByRole('button', { name: '다시 시작', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: '다시 시작', exact: true }).click();
  await expect(row.getByRole('button', { name: '등록 중', exact: true })).toBeDisabled();
  await expect(row.getByRole('button', { name: '삭제', exact: true })).toBeDisabled();
  expect(attempts).toBe(1);
  await pending!.fulfill({ json: { job_id: '920003', state: 'pending', restart_of_run_id: '920002', created: false } });
  await expect(page.locator('#main-content').getByRole('status')).toContainText('이미 진행 중인 재시작 작업을 사용합니다.');
  await expect(page.getByRole('link', { name: '작업 보기', exact: true })).toHaveAttribute('href', '/jobs/920003');
});
test('중지 요청 성공을 즉시 취소 완료로 오인하지 않는다', async ({ page }, info) => {
  fault(info); await page.route('**/api/v1/runs/920001/stop', r => r.fulfill({ json: { job_id: '920001', state: 'running' } }));
  await jobFixture(page); const row = page.locator('tr').filter({ hasText: 'E2E running' });
  await row.getByRole('button', { name: '중지', exact: true }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: '중지', exact: true }).click();
  await expect(page.locator('#main-content').getByRole('status')).toContainText('중지를 요청했습니다.');
  await expect(row.getByRole('button', { name: '중지', exact: true })).toBeEnabled();
});

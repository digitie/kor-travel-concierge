import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';

const backendURL = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:18080';
const repoRoot = path.resolve(__dirname, '../..');
const backendDir = path.join(repoRoot, 'backend');
const seedScript = path.join(repoRoot, 'tests/scripts/seed_e2e.py');
const e2eAdminUsername = process.env.KTC_E2E_ADMIN_USERNAME ?? 'admin';
const e2eAdminPassword = process.env.KTC_E2E_ADMIN_PASSWORD ?? 'e2e-admin-password';

test.describe('Kor Travel Concierge E2E 검증', () => {
  // live 모드(n150)는 로컬 시드/로컬 backend가 없으므로 live-shell.spec.ts만 실행한다.
  test.skip(
    process.env.KTC_LIVE_E2E === '1',
    'live 모드에서는 로컬 시드 기반 스펙을 건너뛴다.',
  );
  test.beforeEach(() => {
    seedE2EData();
  });

  test('결과 화면이 장소 목록·지도·작업 상태·내비를 렌더링한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);

    await expectSeedReady(page);
    await loginAsAdmin(page, '/');

    await expect(page).toHaveTitle(/Korea Travel Concierge/);
    // 결과(/) = 확정 장소 목록 + 지도 + 헤더 작업 상태(상세는 /status로 분리, T-097+)
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
    await expect(page.getByRole('link', { name: /작업 상태/ })).toBeVisible();
    // 멀티페이지 내비(결과/수집/검수) 링크를 접근성 role로 확인한다.
    const nav = page.getByRole('navigation');
    await expect(nav.getByRole('link', { name: '수집' })).toBeVisible();
    await expect(nav.getByRole('link', { name: '검수' })).toBeVisible();

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('수집 화면에서 수집 시작 시 job_id·pending을 표시한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const queueRequests: string[] = [];
    let harvestResponseSeen = false;
    let queueRequestsAfterHarvestResponse = 0;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname !== '/api/v1/runs/queue') return;
      queueRequests.push(url.toString());
      if (harvestResponseSeen) {
        queueRequestsAfterHarvestResponse += 1;
      }
    });
    page.on('response', (response) => {
      const url = new URL(response.url());
      if (
        url.pathname === '/api/v1/harvest' &&
        response.request().method() === 'POST'
      ) {
        harvestResponseSeen = true;
      }
    });
    await loginAsAdmin(page, '/collect');
    await expect.poll(() => queueRequests.length).toBe(1);

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
    // 10초 interval을 기다리지 않고 mutation onSuccess가 공용 queue를 즉시 갱신한다.
    await expect
      .poll(() => queueRequestsAfterHarvestResponse, { timeout: 3_000 })
      .toBe(1);

    // 수집 폼 성공 안내(작업 링크 포함)와 진행 중 작업 패널 표시를 확인한다.
    await expect(page.getByText('수집 작업을 등록했습니다')).toBeVisible();
    await expect(
      page.getByRole('link', { name: '진행 상황 보기' }),
    ).toHaveAttribute('href', `/jobs/${job.job_id}`);

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('작업 상태는 단일 큐 요청으로 실행·대기·확인 필요 수를 공유한다', async ({
    page,
  }) => {
    test.setTimeout(45_000);
    const errors = collectConsoleErrors(page);
    const queueRequests: string[] = [];
    const queueRequestTimes: number[] = [];
    const queueResponseTimes: number[] = [];
    const legacyQueueRequests: string[] = [];
    const historyRequests: URL[] = [];
    let attentionFirstPage:
      | {
          items: Array<Record<string, unknown>>;
          [key: string]: unknown;
        }
      | undefined;
    await page.route('**/api/v1/runs/queue', async (route) => {
      const response = await route.fetch();
      const snapshot = (await response.json()) as Record<string, unknown>;
      await route.fulfill({
        status: response.status(),
        contentType: 'application/json',
        body: JSON.stringify({
          ...snapshot,
          running_count: 101,
          pending_count: 17,
          open_attention_count: 81,
          has_more: true,
        }),
      });
    });
    await page.route('**/api/v1/runs?**', async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get('attention') !== 'open') {
        await route.continue();
        return;
      }
      if (url.searchParams.get('cursor') === 'mock-attention-next') {
        const source = attentionFirstPage?.items[0];
        if (!source) throw new Error('attention 첫 page가 먼저 필요합니다');
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [
              {
                ...source,
                job_id: '81000',
                target_id: 'oldest-open-attention',
                target_label: '가장 오래된 확인 필요 작업',
              },
            ],
            next_cursor: null,
            has_more: false,
            total: 81,
            newest_id: 81000,
            newer_than: 0,
          }),
        });
        return;
      }
      const response = await route.fetch();
      const firstPage = (await response.json()) as typeof attentionFirstPage;
      if (!firstPage) throw new Error('attention 응답이 비어 있습니다');
      attentionFirstPage = firstPage;
      await route.fulfill({
        status: response.status(),
        contentType: 'application/json',
        body: JSON.stringify({
          ...firstPage,
          next_cursor: 'mock-attention-next',
          has_more: true,
          total: 81,
        }),
      });
    });
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname === '/api/v1/runs/queue') {
        queueRequests.push(url.toString());
        queueRequestTimes.push(Date.now());
      }
      if (
        url.pathname === '/api/v1/runs' &&
        ['running', 'pending'].includes(url.searchParams.get('state') ?? '')
      ) {
        legacyQueueRequests.push(url.toString());
      }
      if (url.pathname === '/api/v1/runs') historyRequests.push(url);
    });
    page.on('response', (response) => {
      const url = new URL(response.url());
      if (url.pathname === '/api/v1/runs/queue') {
        queueResponseTimes.push(Date.now());
      }
    });

    await loginAsAdmin(page, '/status');

    const statusLink = page.getByRole('link', {
      name: /작업 상태: 실행 101, 대기 17, 확인 필요 81\./,
    });
    await expect(statusLink).toBeVisible();
    await expect(statusLink.getByText('118', { exact: true })).toBeVisible();
    await expect(statusLink.getByText('확인 81', { exact: true })).toBeVisible();
    await expect(
      page.getByText('실행 101 · 대기 17 · 확인 필요 81', { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText('활성 작업 총 118건 중 1건 표시', { exact: true }),
    ).toBeVisible();
    await expect.poll(() => queueRequests.length).toBe(1);
    await page.waitForTimeout(250);
    expect(queueRequests).toHaveLength(1);
    expect(legacyQueueRequests).toEqual([]);

    // status와 collect observer가 같은 fresh cache를 쓰므로 client navigation 직후에는
    // queue를 다시 요청하지 않고, 10초 interval에서만 다음 1회가 나간다.
    await page
      .getByRole('navigation')
      .getByRole('link', { name: '수집', exact: true })
      .click();
    await expect(page).toHaveURL(/\/collect$/);
    await page.waitForTimeout(250);
    expect(queueRequests).toHaveLength(1);
    await expect
      .poll(() => queueRequests.length, {
        timeout: 12_500,
        intervals: [250],
      })
      .toBe(2);
    expect(queueRequestTimes[1] - queueResponseTimes[0]).toBeGreaterThanOrEqual(
      9_000,
    );
    expect(queueRequestTimes[1] - queueResponseTimes[0]).toBeLessThanOrEqual(
      10_750,
    );
    await page.waitForTimeout(500);
    expect(queueRequests).toHaveLength(2);
    expect(legacyQueueRequests).toEqual([]);
    expect(historyRequests.length).toBeGreaterThan(0);
    expect(
      historyRequests.every(
        (url) => url.searchParams.get('terminal') === 'true',
      ),
    ).toBe(true);
    expect(
      historyRequests.every(
        (url) => url.searchParams.get('user_jobs_only') === 'true',
      ),
    ).toBe(true);

    // attention 배지는 단순 상태 페이지가 아니라 확인할 실패 이력으로 바로 이동한다.
    const attentionLink = page.getByRole('link', {
      name: /작업 상태: 실행 101, 대기 17, 확인 필요 81\./,
    });
    await attentionLink.click();
    await expect(page).toHaveURL(
      /\/status\?tab=history&attention=open$/,
    );
    await expect
      .poll(() =>
        historyRequests.some(
          (url) => url.searchParams.get('attention') === 'open',
        ),
      )
      .toBe(true);
    const historyTab = page.getByRole('tab', { name: /확인 필요/ });
    await expect(historyTab).toHaveAttribute('aria-selected', 'true');
    await expect(
      page.getByRole('row', { name: /실패 재시작 E2E/ }),
    ).toBeVisible();
    await page
      .getByRole('button', { name: '다음 작업 이력 불러오기 (1/81)' })
      .click();
    await expect(
      page.getByRole('row', { name: /가장 오래된 확인 필요 작업/ }),
    ).toBeVisible();
    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('큐 오류 중 화면을 이동해도 재시도 주기가 폭주하지 않는다', async ({
    page,
  }) => {
    test.setTimeout(30_000);
    let queueRequestCount = 0;
    let historyRequestCount = 0;
    await page.route('**/api/v1/runs/queue', async (route) => {
      queueRequestCount += 1;
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '일시적인 큐 장애' }),
      });
    });
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (
        url.pathname === '/api/v1/runs' &&
        url.searchParams.get('terminal') === 'true' &&
        url.searchParams.get('user_jobs_only') === 'true'
      ) {
        historyRequestCount += 1;
      }
    });

    await loginAsAdmin(page, '/status');
    const statusLink = page.getByRole('link', {
      name: /작업 상태: 실행 0, 대기 0, 확인 필요 0\. 작업 상태 오류/,
    });
    await expect(statusLink.getByText('오류', { exact: true })).toBeVisible();
    expect(historyRequestCount).toBeGreaterThanOrEqual(1);
    await page.getByRole('tab', { name: /완료 이력/ }).click();
    await expect(
      page.getByRole('row', { name: /실패 재시작 E2E/ }),
    ).toBeVisible();
    const requestsAfterInitialRetry = queueRequestCount;
    expect(requestsAfterInitialRetry).toBeGreaterThanOrEqual(2);

    await page
      .getByRole('navigation')
      .getByRole('link', { name: '수집', exact: true })
      .click();
    await page
      .getByRole('navigation')
      .getByRole('link', { name: '검수', exact: true })
      .click();
    await page.waitForTimeout(500);
    expect(queueRequestCount).toBe(requestsAfterInitialRetry);

    await expect
      .poll(() => queueRequestCount, {
        timeout: 10_750,
        intervals: [100],
      })
      .toBe(requestsAfterInitialRetry + 1);
  });

  test('종료 작업 이력은 60초 safety 주기로 갱신한다', async ({ page }) => {
    test.setTimeout(80_000);
    let historyRequestCount = 0;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (
        url.pathname === '/api/v1/runs' &&
        url.searchParams.get('terminal') === 'true' &&
        url.searchParams.get('user_jobs_only') === 'true'
      ) {
        historyRequestCount += 1;
      }
    });

    await loginAsAdmin(page, '/status');
    await expect.poll(() => historyRequestCount).toBe(1);

    await page.waitForTimeout(61_500);

    await expect.poll(() => historyRequestCount).toBe(2);
  });

  test('실패·쿼터 보류 작업을 멱등 재시작하고 lineage·attention을 표시한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    await loginAsAdmin(page, '/status');
    await page.getByRole('tab', { name: /완료 이력/ }).click();

    const failedRow = page.getByRole('row', { name: /실패 재시작 E2E/ });
    await expect(failedRow).toBeVisible();
    await expect(failedRow.getByText('확인 필요', { exact: true })).toBeVisible();

    const firstRestartResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/runs/') &&
        response.url().endsWith('/restart') &&
        response.request().method() === 'POST',
    );
    await failedRow
      .getByRole('button', { name: '다시 시작', exact: true })
      .click();
    const firstDialog = page.getByRole('alertdialog');
    await expect(firstDialog).toContainText('같은 입력으로 새 작업을 등록합니다');
    await firstDialog
      .getByRole('button', { name: '다시 시작', exact: true })
      .click();
    const firstRestart = await firstRestartResponse;
    expect(firstRestart.ok()).toBeTruthy();
    const firstResult = (await firstRestart.json()) as {
      job_id: string;
      restart_of_run_id: string;
      created: boolean;
    };
    expect(firstResult.created).toBe(true);

    await expect(failedRow.getByText('재시작됨', { exact: true })).toBeVisible();
    await expect(page.getByRole('status')).toContainText(
      '새 재시작 작업을 등록했습니다.',
    );

    const duplicateRestartResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/runs/') &&
        response.url().endsWith('/restart') &&
        response.request().method() === 'POST',
    );
    await failedRow
      .getByRole('button', { name: '다시 시작', exact: true })
      .click();
    await page
      .getByRole('alertdialog')
      .getByRole('button', { name: '다시 시작', exact: true })
      .click();
    const duplicateRestart = await duplicateRestartResponse;
    const duplicateResult = (await duplicateRestart.json()) as {
      job_id: string;
      created: boolean;
    };
    expect(duplicateResult).toEqual({
      job_id: firstResult.job_id,
      created: false,
      state: 'pending',
      restart_of_run_id: firstResult.restart_of_run_id,
    });
    await expect(page.getByRole('status')).toContainText(
      '이미 진행 중인 재시작 작업을 사용합니다.',
    );

    await page.getByRole('status').getByRole('link', { name: '작업 보기' }).click();
    await expect(page).toHaveURL(new RegExp(`/jobs/${firstResult.job_id}$`));
    await expect(page.getByRole('link', { name: /원본 작업 #/ })).toHaveAttribute(
      'href',
      `/jobs/${firstResult.restart_of_run_id}`,
    );

    await page.goto('/status');
    await page.getByRole('tab', { name: /완료 이력/ }).click();
    const deferredRow = page.getByRole('row', { name: /쿼터 보류 E2E/ });
    await expect(deferredRow.getByText('쿼터 보류', { exact: true })).toBeVisible();
    const deferredDetailLink = deferredRow.getByRole('link', {
      name: '상세',
      exact: true,
    });
    const deferredDetailHref = await deferredDetailLink.getAttribute('href');
    expect(deferredDetailHref).toMatch(/^\/jobs\/\d+$/);
    await deferredDetailLink.click();
    await expect(page).toHaveURL(new RegExp(`${deferredDetailHref}$`));
    await expect(page.getByText('쿼터 보류', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('쿼터로 처리 보류', { exact: true })).toBeVisible();

    const deferredRestartResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/runs/') &&
        response.url().endsWith('/restart') &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '다시 시작', exact: true }).click();
    await page
      .getByRole('alertdialog')
      .getByRole('button', { name: '다시 시작', exact: true })
      .click();
    const deferredRestart = await deferredRestartResponse;
    const deferredResult = (await deferredRestart.json()) as { job_id: string };
    await expect(page).toHaveURL(new RegExp(`/jobs/${deferredResult.job_id}$`));

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('실행 중 작업을 확인 후 중지 요청하고 즉시 상태를 갱신한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    const facetRequests: string[] = [];
    let hideRunningQueue = false;
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.pathname === '/api/v1/destinations/facets') {
        facetRequests.push(url.toString());
      }
    });
    await page.route('**/api/v1/runs/queue', async (route) => {
      if (!hideRunningQueue) {
        await route.continue();
        return;
      }
      const response = await route.fetch();
      const snapshot = (await response.json()) as {
        items: Array<{ state: string }>;
        open_attention_count: number;
        running_count: number;
        pending_count: number;
        has_more: boolean;
        user_job_types: string[];
      };
      await route.fulfill({
        status: response.status(),
        contentType: 'application/json',
        body: JSON.stringify({
          ...snapshot,
          items: snapshot.items.filter((run) => run.state !== 'running'),
          running_count: 0,
        }),
      });
    });
    await page.route('**/api/v1/runs/*/stop', async (route) => {
      const response = await route.fetch();
      hideRunningQueue = true;
      await route.fulfill({ response });
    });
    // 결과 화면에서 facet cache를 먼저 만든 뒤 상태 화면으로 이동한다.
    await loginAsAdmin(page, '/');
    await expect.poll(() => facetRequests.length).toBe(1);
    await page
      .getByRole('navigation')
      .getByRole('link', { name: '상태', exact: true })
      .click();
    await expect(page).toHaveURL(/\/status$/);

    const runningRow = page.getByRole('row', { name: /부산 맛집/ });
    await expect(runningRow).toBeVisible();
    const stopResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/runs/') &&
        response.url().endsWith('/stop') &&
        response.request().method() === 'POST',
    );
    await runningRow.getByRole('button', { name: '중지', exact: true }).click();
    const stopDialog = page.getByRole('alertdialog');
    await expect(stopDialog).toContainText('이미 저장된 결과는 유지됩니다');
    await stopDialog.getByRole('button', { name: '중지', exact: true }).click();
    const stopped = await stopResponse;
    expect(stopped.ok()).toBeTruthy();
    const stopResult = (await stopped.json()) as {
      state: string;
    };
    expect(stopResult.state).toBe('running');
    await expect(runningRow).toHaveCount(0);
    await expect(page.getByRole('status')).toContainText('중지를 요청했습니다.');

    // queue poll에서 활성 ID가 사라지면 10분 stale cache에 묶이지 않고
    // 결과 화면 복귀 즉시 facet을 다시 읽는다.
    await page
      .getByRole('navigation')
      .getByRole('link', { name: '결과', exact: true })
      .click();
    await expect(page).toHaveURL(/\/$/);
    await expect
      .poll(() => facetRequests.length, { timeout: 3_000 })
      .toBe(2);
    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('Deep Research(상세 모달)와 검수 저장이 API·UI에 반영된다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await expectSeedReady(page);

    // Part A: 결과 화면에서 장소 상세 모달을 열고 Deep Research(상세 모달로 이동, T-107)
    await loginAsAdmin(page, '/');
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
        const runs = (await response.json()) as {
          items: Array<{ job_type: string }>;
        };
        return runs.items.some((run) => run.job_type === 'deep_research');
      })
      .toBe(true);

    // Part B: 검수 화면에서 후보를 확정 저장
    await page.goto('/review');
    await page.getByRole('row', { name: /성산 일출봉 카페/ }).click();
    await page.getByLabel('확정 장소명').fill('성산 일출봉 카페');
    await page.getByLabel('위도').fill('33.4581');
    await page.getByLabel('경도').fill('126.9425');
    const resolveResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/destinations/unmatched/') &&
        response.url().endsWith('/resolve') &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '저장', exact: true }).click();
    expect((await resolveResponse).ok()).toBeTruthy();

    await expect
      .poll(async () => {
        const response = await page.request.get(`${backendURL}/api/v1/destinations/unmatched`);
        const candidates = (await response.json()) as { items: unknown[] };
        return candidates.items.length;
      })
      .toBe(0);

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('provider 선택 provenance와 근접 신규 생성 결정을 보존한다', async ({ page }) => {
    const resolveBodies: Array<Record<string, unknown>> = [];
    await page.route('**/api/v1/place-search?**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          query: '제주 서귀포 성산 일출봉 카페',
          searched_at: '2026-07-13T01:00:00Z',
          google: [
            {
              provider: 'google',
              native_id: 'google-blocked-1',
              name: 'Google 정책 장소',
              address: '제주 Google 주소',
              road_address: null,
              latitude: 33.45,
              longitude: 126.94,
              category: '카페',
              storage_allowed: false,
              storage_block_reason: '정책 결정 전에는 저장할 수 없습니다.',
            },
          ],
          kakao: [
            {
              provider: 'kakao',
              native_id: 'kakao-selected-1',
              name: 'Kakao 저장 장소',
              address: '제주 서귀포시 성산읍 1',
              road_address: '제주 서귀포시 성산로 1',
              latitude: 33.55631,
              longitude: 126.79581,
              category: '음식점 > 카페',
              storage_allowed: true,
              storage_block_reason: null,
            },
          ],
          naver: [],
          errors: {},
        }),
      });
    });
    await page.route('**/api/v1/categories/match?**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ match: null }),
      });
    });
    await page.route('**/api/v1/destinations/unmatched/*/resolve', async (route) => {
      resolveBodies.push(route.request().postDataJSON() as Record<string, unknown>);
      if (resolveBodies.length === 1) {
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: {
              code: 'nearby_place_confirmation_required',
              nearby_places: [
                {
                  place_id: 9001,
                  name: '근접 기존 장소',
                  official_address: '제주 서귀포시',
                  road_address: null,
                  latitude: 33.5563,
                  longitude: 126.7958,
                  api_source: 'manual',
                  distance_m: 18.4,
                  name_compatible: false,
                  provider_id_match: null,
                },
              ],
            },
          }),
        });
        return;
      }
      await route.continue();
    });

    await loginAsAdmin(page, '/review');
    await page.getByRole('row', { name: /성산 일출봉 카페/ }).click();
    const googleHit = page.getByRole('button', { name: /Google 정책 장소/ });
    await expect(googleHit).toBeDisabled();
    await page.getByRole('button', { name: /^Kakao 저장 장소/ }).click();
    await expect(page.getByText('선택 원본')).toBeVisible();
    await expect(
      page
        .getByRole('region', { name: 'VWorld 지도' })
        .getByRole('button', { name: /Google 정책 장소/ }),
    ).toHaveCount(0);

    await page.getByRole('button', { name: '저장', exact: true }).click();
    const conflictDialog = page.getByRole('alertdialog');
    await expect(conflictDialog).toBeVisible();
    await expect(
      conflictDialog.getByLabel('근접 중복 확인 대상').getByText('Kakao 저장 장소', {
        exact: true,
      }),
    ).toBeVisible();
    await expect(conflictDialog.getByText('이름 불일치')).toBeVisible();
    await expect(conflictDialog.getByText('provider ID 비교 불가')).toBeVisible();
    const retryResponse = page.waitForResponse(
      (response) =>
        response.url().includes('/api/v1/destinations/unmatched/') &&
        response.url().endsWith('/resolve') &&
        response.request().method() === 'POST',
    );
    await conflictDialog.getByRole('button', { name: '새 장소로 만들기' }).click();
    expect((await retryResponse).ok()).toBeTruthy();

    await expect.poll(() => resolveBodies.length).toBe(2);
    expect(resolveBodies[0]).toMatchObject({
      action: 'create_place',
      corrected_name: 'Kakao 저장 장소',
      official_address: '제주 서귀포시 성산읍 1',
      road_address: '제주 서귀포시 성산로 1',
      api_source: 'kakao',
      selected_hit: {
        provider: 'kakao',
        native_id: 'kakao-selected-1',
        query: '제주 서귀포 성산 일출봉 카페',
        searched_at: '2026-07-13T01:00:00Z',
      },
    });
    expect(resolveBodies[1]).toMatchObject({
      ...resolveBodies[0],
      duplicate_resolution: 'create_new',
    });
  });

  test('설정 화면에서 AI 엔진을 저장한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await loginAsAdmin(page, '/settings');

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

    const scopeSelect = page.getByLabel('공개 API 키 권한');
    await expect(scopeSelect).toContainText('읽기 전용');
    await page.getByLabel('공개 API 키 라벨').fill('E2E 외부 소비자');
    const createReadKeyResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/v1/admin/public-api-keys') &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '생성', exact: true }).click();
    const createdReadKey = await createReadKeyResponse;
    expect(createdReadKey.ok()).toBeTruthy();
    expect(createdReadKey.request().postDataJSON()).toMatchObject({
      label: 'E2E 외부 소비자',
      scope: 'read',
    });
    expect((await createdReadKey.json()).item.scope).toBe('read');
    await expect(page.getByText(/끝자리 .* · 읽기 전용 · 활성/)).toBeVisible();

    await page.getByLabel('공개 API 키 라벨').fill('E2E 운영 자동화');
    await page.getByLabel('공개 API 키 권한').click();
    await page.getByRole('option', { name: '관리자', exact: true }).click();
    const createKeyResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/v1/admin/public-api-keys') &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '생성', exact: true }).click();
    const createdKey = await createKeyResponse;
    expect(createdKey.ok()).toBeTruthy();
    expect((await createdKey.json()).item).toMatchObject({
      label: 'E2E 운영 자동화',
      scope: 'admin',
      state: 'active',
    });
    await expect(page.getByLabel('생성된 공개 API 키')).toBeVisible();
    await expect(page.getByText(/끝자리 .* · 관리자 · 활성/)).toBeVisible();

    expectRelevantConsoleErrors(errors).toEqual([]);
  });
});

test.describe('장소 cursor 페이지네이션 E2E 검증', () => {
  test.skip(
    process.env.KTC_LIVE_E2E === '1',
    'live 모드에서는 browser API mock 기반 스펙을 건너뛴다.',
  );

  test('100개 page를 cursor로 이어 마지막 장소까지 중복 없이 더 불러온다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests = await installDestinationPaginationMock(page);

    await loginAsAdmin(page, '/');

    const placesRegion = page.getByRole('region', { name: '장소 목록' });
    await expect(placesRegion).toBeVisible();
    await expect.poll(() => requests.list.length).toBeGreaterThan(0);

    const firstPageRequest = new URL(requests.list[0]);
    expect(firstPageRequest.searchParams.get('limit')).toBe('100');
    expect(firstPageRequest.searchParams.get('cursor')).toBeNull();

    const marker100 = placesRegion.locator('[data-marker-number="100"]');
    await marker100.scrollIntoViewIfNeeded();
    await expect(marker100).toBeVisible();
    const marker101 = placesRegion.locator('[data-marker-number="101"]');
    await expect(marker101).toHaveCount(0);
    await expect(
      placesRegion.getByRole('button', {
        name: '페이지 장소 100 상세',
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      placesRegion.getByText(/총\s*501개\s*중\s*100개\s*표시|100\s*\/\s*501/),
    ).toBeVisible();

    await loadMoreDestinationPage(page, placesRegion, 'page-2');
    await marker101.scrollIntoViewIfNeeded();
    await expect(marker101).toBeVisible();
    await expect(
      placesRegion.getByRole('button', {
        name: '페이지 장소 101 상세',
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      placesRegion.getByRole('button', {
        name: '갱신된 페이지 장소 100 상세',
        exact: true,
      }),
    ).toHaveCount(1);
    await expect(
      placesRegion.getByRole('button', {
        name: '페이지 장소 100 상세',
        exact: true,
      }),
    ).toHaveCount(0);

    for (const cursor of ['page-3', 'page-4', 'page-5', 'page-6']) {
      await loadMoreDestinationPage(page, placesRegion, cursor);
    }

    const marker501 = placesRegion.locator('[data-marker-number="501"]');
    await marker501.scrollIntoViewIfNeeded();
    await expect(marker501).toBeVisible();
    await expect(
      placesRegion.getByRole('button', {
        name: '페이지 장소 501 상세',
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      placesRegion.getByText('총 501개를 모두 불러왔습니다.', { exact: true }),
    ).toBeVisible();
    await expect(
      placesRegion.getByRole('button', { name: '장소 더 불러오기' }),
    ).toHaveCount(0);

    const markerNumbers = await placesRegion
      .locator('[data-marker-number]')
      .evaluateAll((elements) =>
        elements.map((element) => element.getAttribute('data-marker-number')),
      );
    expect(markerNumbers).toHaveLength(501);
    expect(new Set(markerNumbers).size).toBe(501);

    const resetRequest = page.waitForRequest((request) => {
      const url = new URL(request.url());
      return (
        url.pathname === '/api/v1/destinations' &&
        url.searchParams.get('sort') === 'latest'
      );
    });
    await placesRegion.getByLabel('장소 정렬').click();
    await page.getByRole('option', { name: '최신 등록 순' }).click();
    const resetURL = new URL((await resetRequest).url());
    expect(resetURL.searchParams.get('cursor')).toBeNull();
    expect(resetURL.searchParams.get('limit')).toBe('100');
    await expect(
      placesRegion.locator('[data-marker-number="101"]'),
    ).toHaveCount(0);

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('첫 page 밖 장소 deep link를 직접 열고 닫을 때 query를 제거한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests = await installDestinationPaginationMock(
      page,
      destinationDetailFixture(501),
    );

    await loginAsAdminWithQuery(page, '/?place=501');

    // modal이 열린 동안 배경은 접근성 tree에서 제외될 수 있으므로 DOM 경계로 확인한다.
    const placesRegion = page.locator('section[aria-label="장소 목록"]');
    await expect(placesRegion).toBeVisible();
    await expect.poll(() => requests.list.length).toBeGreaterThan(0);
    await expect(
      placesRegion.locator('[data-marker-number="100"]'),
    ).toHaveCount(1);
    await expect(
      placesRegion.locator('button[aria-label="페이지 장소 501 상세"]'),
    ).toHaveCount(0);
    await expect.poll(() => requests.detail.length).toBeGreaterThan(0);
    expect(new URL(requests.detail[0]).pathname).toBe(
      '/api/v1/destinations/501/detail',
    );

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByText('페이지 밖 장소 501', { exact: true }),
    ).toBeVisible();
    await dialog.getByRole('button', { name: '닫기' }).click();

    await expect(dialog).toBeHidden();
    await expect
      .poll(() => new URL(page.url()).searchParams.has('place'))
      .toBe(false);
    expect(new URL(page.url()).pathname).toBe('/');

    expectRelevantConsoleErrors(errors).toEqual([]);
  });
});

test.describe('검수 큐 자동 진행 E2E 검증', () => {
  test.skip(
    process.env.KTC_LIVE_E2E === '1',
    'live 모드에서는 browser API mock 기반 스펙을 건너뛴다.',
  );

  test('저장·제외·page 끝 개별 삭제 뒤 다음 page 후보를 자동 선택한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests = await installReviewQueueMock(page);

    await loginAsAdmin(page, '/review');

    const searchInput = page.getByPlaceholder(
      '장소명으로 검색 (Google·Kakao·Naver·Gemini)',
    );
    await expect(searchInput).toHaveValue('자동 후보 1');
    for (const name of ['자동 후보 1', '자동 후보 2', '자동 후보 3']) {
      await expect(
        page.getByRole('row', { name: new RegExp(`${name}(?!\\d)`) }),
      ).toBeVisible();
    }
    await page.waitForTimeout(250);
    expect(requests.searchQueries).toEqual([]);

    await expect(page.getByRole('link', { name: /영상 보기/ })).toHaveAttribute(
      'href',
      'https://www.youtube.com/watch?v=review-video-1&t=754s',
    );

    const groundingFilter = page.getByRole('combobox', {
      name: '원문 근거 필터',
    });
    await groundingFilter.click();
    await page.getByRole('option', { name: '원문 근거 확인' }).click();
    await expect(groundingFilter).toContainText('원문 근거 확인');
    await expect.poll(() => requests.groundingFilters).toContain('verified_raw');
    await expect
      .poll(() =>
        requests.newerProbeRequests.some(
          (url) => url.searchParams.get('grounding') === 'verified_raw',
        ),
      )
      .toBe(true);

    const domesticFilter = page.getByRole('combobox', {
      name: '국내 여부 필터',
    });
    await domesticFilter.click();
    await page.getByRole('option', { name: '국내 판정만' }).click();
    await expect(domesticFilter).toContainText('국내 판정만');
    await expect.poll(() => requests.domesticFilters).toContain('true');
    await expect
      .poll(() =>
        requests.mainListRequests.some(
          (url) =>
            url.searchParams.get('is_domestic') === 'true' &&
            url.searchParams.get('grounding') === 'verified_raw' &&
            url.searchParams.get('cursor') === null,
        ),
      )
      .toBe(true);
    await expect(page.getByText('300/301개 불러옴')).toBeVisible();
    await expect(searchInput).toHaveValue('자동 후보 1');

    const firstRow = page.getByRole('row', { name: /자동 후보 1(?!\d)/ });
    await expect(firstRow).toHaveAttribute('aria-selected', 'true');
    await expect(firstRow).toContainText('자동 검수 영상 1');
    await expect(firstRow).toContainText('자동 검수 채널');
    await expect(firstRow).toContainText('매칭 신뢰도 83%');
    await expect(firstRow).toContainText('추출 직후');
    await expect(firstRow).toContainText('원문 근거 확인');
    await expect(firstRow).toContainText('등록');
    await firstRow.click();
    await expect.poll(() => requests.searchQueries).toContain('자동 후보 1');
    await page
      .getByRole('button', { name: /^검색 결과 자동 후보 1/ })
      .click();
    await page.getByRole('button', { name: '저장', exact: true }).click();

    await expect.poll(() => requests.resolveBodies.length).toBe(1);
    expect(requests.resolveBodies[0]).toMatchObject({ action: 'create_place' });
    await expect(searchInput).toHaveValue('자동 후보 2');
    await expect(
      page.getByRole('row', { name: /자동 후보 2(?!\d)/ }),
    ).toHaveAttribute('aria-selected', 'true');
    await expect.poll(() => requests.searchQueries).toContain('자동 후보 2');

    await page.getByRole('button', { name: '제외', exact: true }).click();
    await expect.poll(() => requests.resolveBodies.length).toBe(2);
    expect(requests.resolveBodies[1]).toMatchObject({ action: 'ignore' });
    await expect(searchInput).toHaveValue('자동 후보 3');
    await expect(
      page.getByRole('row', { name: /자동 후보 3(?!\d)/ }),
    ).toHaveAttribute('aria-selected', 'true');
    await expect.poll(() => requests.searchQueries).toContain('자동 후보 3');

    const pageTailRow = page.getByRole('row', { name: /자동 후보 300/ });
    await pageTailRow.click();
    await expect(pageTailRow).toHaveAttribute('aria-selected', 'true');
    await expect(searchInput).toHaveValue('자동 후보 300');
    await expect.poll(() => requests.searchQueries).toContain('자동 후보 300');
    await page
      .getByRole('button', { name: '자동 후보 300 후보 삭제', exact: true })
      .click();
    await page.getByRole('button', { name: '삭제', exact: true }).click();
    await expect.poll(() => requests.deleteCandidateIds).toEqual([300]);

    await expect
      .poll(() =>
        requests.listCursorPayloads.some(
          (cursor) =>
            cursor.sort === 'oldest' &&
            cursor.status === 'needs_review' &&
            cursor.filter.isDomestic === 'true' &&
            cursor.filter.grounding === 'verified_raw' &&
            cursor.snapshotId === 301 &&
            cursor.lastId === 300,
        ),
      )
      .toBe(true);
    await expect(searchInput).toHaveValue('자동 후보 301');
    await expect.poll(() => requests.searchQueries).toContain('자동 후보 301');
    await expect(
      page.getByRole('row', { name: /해외 숨김 후보/ }),
    ).toHaveCount(0);

    expect(requests.resolveBodies.map((body) => body.action)).toEqual([
      'create_place',
      'ignore',
    ]);
    expect(requests.resolveCandidateIds).toEqual([1, 2]);
    expect(
      [...requests.processedCandidateIds].sort((left, right) => left - right),
    ).toEqual([1, 2, 300]);
    await expect(page.getByText('298/298개 불러옴')).toBeVisible();

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('국내 판정 filter를 서버에 보내 해외 후보가 page 예산을 쓰지 않게 한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests = await installReviewQueueMock(page, {
      initialHiddenOnly: true,
    });

    await loginAsAdmin(page, '/review');

    const domesticFilter = page.getByRole('combobox', {
      name: '국내 여부 필터',
    });
    await domesticFilter.click();
    await page.getByRole('option', { name: '국내 판정만' }).click();
    await expect(domesticFilter).toContainText('국내 판정만');
    await expect.poll(() => requests.domesticFilters).toContain('true');
    await expect
      .poll(() =>
        requests.mainListRequests.some(
          (url) =>
            url.searchParams.get('is_domestic') === 'true' &&
            url.searchParams.get('cursor') === null,
        ),
      )
      .toBe(true);
    await expect(page.getByText('1/1개 불러옴')).toBeVisible();
    await expect(page.getByRole('button', { name: '후보 더 불러오기' })).toHaveCount(
      0,
    );
    await expect(page.getByRole('row', { name: /뒤 page 국내 후보/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(
      page.getByPlaceholder('장소명으로 검색 (Google·Kakao·Naver·Gemini)'),
    ).toHaveValue('뒤 page 국내 후보');
    await page.waitForTimeout(250);
    expect(requests.searchQueries).toEqual([]);
    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('resolve 409 후 non-actionable 상세를 확인하고 stale 패널을 닫는다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests = await installReviewQueueMock(page, {
      firstResolveExternallyProcessed: true,
    });

    await loginAsAdminWithQuery(page, '/review?sort=oldest&is_domestic=true');
    const searchInput = page.getByPlaceholder(
      '장소명으로 검색 (Google·Kakao·Naver·Gemini)',
    );
    await expect(searchInput).toHaveValue('자동 후보 1');

    await page.getByRole('button', { name: '제외', exact: true }).click();
    await expect.poll(() => requests.resolveCandidateIds).toEqual([1]);
    await expect
      .poll(() =>
        requests.detailResponses
          .filter(({ candidateId }) => candidateId === 1)
          .at(-1),
      )
      .toEqual({ candidateId: 1, status: 200, matchStatus: 'ignored' });
    await expect(
      page
        .getByRole('alert')
        .filter({ hasText: '처리 결과를 확인하지 못했습니다' }),
    ).toBeVisible();
    await expect(searchInput).toHaveValue('자동 후보 2');
    await expect(
      page.getByRole('row', { name: /자동 후보 2(?!\d)/ }),
    ).toHaveAttribute('aria-selected', 'true');
    await expect(
      page.getByRole('row', { name: /자동 후보 1(?!\d)/ }),
    ).toHaveCount(0);

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('resolve 409 중 A→B→A로 다시 선택해도 처리된 A의 stale workflow를 정리한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests = await installReviewQueueMock(page, {
      firstResolveExternallyProcessed: true,
      holdFirstResolveExternallyProcessed: true,
    });

    await loginAsAdminWithQuery(page, '/review?sort=oldest&is_domestic=true');
    const searchInput = page.getByPlaceholder(
      '장소명으로 검색 (Google·Kakao·Naver·Gemini)',
    );
    const firstRow = page.getByRole('row', { name: /자동 후보 1(?!\d)/ });
    const secondRow = page.getByRole('row', { name: /자동 후보 2(?!\d)/ });
    await expect(searchInput).toHaveValue('자동 후보 1');
    const firstCheckbox = firstRow.getByRole('checkbox');
    await firstCheckbox.click();
    await expect(firstCheckbox).toBeChecked();

    const resolveResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          '/api/v1/destinations/unmatched/1/resolve' &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '제외', exact: true }).click();
    await expect.poll(() => requests.resolveCandidateIds).toEqual([1]);
    await secondRow.click();
    await expect(searchInput).toHaveValue('자동 후보 2');
    await firstRow.click();
    await expect(searchInput).toHaveValue('자동 후보 1');

    requests.releaseFirstResolveResponse();
    expect((await resolveResponsePromise).status()).toBe(409);
    await expect
      .poll(() =>
        requests.detailResponses
          .filter(({ candidateId }) => candidateId === 1)
          .at(-1),
      )
      .toEqual({ candidateId: 1, status: 200, matchStatus: 'ignored' });
    await expect(searchInput).toHaveValue('자동 후보 2');
    await expect(secondRow).toHaveAttribute('aria-selected', 'true');
    await expect(firstRow).toHaveCount(0);

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('page 밖 resolve 409 뒤 non-actionable 상세이면 URL을 지우고 첫 후보로 복귀한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests = await installReviewQueueMock(page, {
      firstResolveExternallyProcessed: true,
    });

    await loginAsAdminWithQuery(
      page,
      '/review?candidate=301&sort=oldest&is_domestic=true',
    );
    const searchInput = page.getByPlaceholder(
      '장소명으로 검색 (Google·Kakao·Naver·Gemini)',
    );
    await expect(searchInput).toHaveValue('자동 후보 301');
    await expect(
      page.getByText(/현재 필터에는 포함되지만 아직 불러온 페이지 밖 후보입니다/),
    ).toBeVisible();

    const resolveResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          '/api/v1/destinations/unmatched/301/resolve' &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '제외', exact: true }).click();

    expect((await resolveResponsePromise).status()).toBe(409);
    await expect.poll(() => requests.resolveCandidateIds).toEqual([301]);
    await expect
      .poll(() =>
        requests.detailResponses
          .filter(({ candidateId }) => candidateId === 301)
          .at(-1),
      )
      .toEqual({ candidateId: 301, status: 200, matchStatus: 'ignored' });
    await expect
      .poll(() => new URL(page.url()).searchParams.get('candidate'))
      .toBeNull();
    await expect(searchInput).toHaveValue('자동 후보 1');
    await expect(
      page.getByRole('row', { name: /자동 후보 1(?!\d)/ }),
    ).toHaveAttribute('aria-selected', 'true');

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('page 밖 resolve 도중 외부 soft delete이면 409·상세 404 뒤 첫 후보로 복귀한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests = await installReviewQueueMock(page, {
      firstResolveExternallyDeleted: true,
    });

    await loginAsAdminWithQuery(
      page,
      '/review?candidate=301&sort=oldest&is_domestic=true',
    );
    const searchInput = page.getByPlaceholder(
      '장소명으로 검색 (Google·Kakao·Naver·Gemini)',
    );
    await expect(searchInput).toHaveValue('자동 후보 301');

    const resolveResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          '/api/v1/destinations/unmatched/301/resolve' &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '제외', exact: true }).click();

    expect((await resolveResponsePromise).status()).toBe(409);
    await expect
      .poll(() =>
        requests.detailResponses
          .filter(({ candidateId }) => candidateId === 301)
          .at(-1),
      )
      .toEqual({ candidateId: 301, status: 404, matchStatus: null });
    await expect
      .poll(() => new URL(page.url()).searchParams.get('candidate'))
      .toBeNull();
    await expect(searchInput).toHaveValue('자동 후보 1');
    await expect(
      page.getByRole('row', { name: /자동 후보 1(?!\d)/ }),
    ).toHaveAttribute('aria-selected', 'true');

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('page 밖 resolve 500 뒤 actionable 상세이면 URL과 선택을 유지한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests = await installReviewQueueMock(page, {
      firstResolveFailsWithoutProcessing: true,
    });

    await loginAsAdminWithQuery(
      page,
      '/review?candidate=301&sort=oldest&is_domestic=true',
    );
    const searchInput = page.getByPlaceholder(
      '장소명으로 검색 (Google·Kakao·Naver·Gemini)',
    );
    await expect(searchInput).toHaveValue('자동 후보 301');

    const resolveResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          '/api/v1/destinations/unmatched/301/resolve' &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '제외', exact: true }).click();

    expect((await resolveResponsePromise).status()).toBe(500);
    await expect
      .poll(() =>
        requests.detailResponses
          .filter(({ candidateId }) => candidateId === 301)
          .at(-1),
      )
      .toEqual({ candidateId: 301, status: 200, matchStatus: 'needs_review' });
    await expect
      .poll(() => new URL(page.url()).searchParams.get('candidate'))
      .toBe('301');
    await expect(searchInput).toHaveValue('자동 후보 301');
    await expect(
      page
        .getByRole('alert')
        .filter({ hasText: '처리 결과를 확인하지 못했습니다' }),
    ).toBeVisible();

    const isExpectedResource500 = (message: string) =>
      message.includes('Failed to load resource') &&
      message.includes('500 (Internal Server Error)');
    await expect
      .poll(() => errors.filter(isExpectedResource500).length)
      .toBe(1);
    expectRelevantConsoleErrors(
      errors.filter((message) => !isExpectedResource500(message)),
    ).toEqual([]);
  });

  test('delete preflight 뒤 외부 soft delete 404와 상세 404를 확인해 modal을 정리한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests = await installReviewQueueMock(page, {
      firstDeleteAlreadySoftDeleted: true,
    });

    await loginAsAdminWithQuery(page, '/review?sort=oldest&is_domestic=true');
    const searchInput = page.getByPlaceholder(
      '장소명으로 검색 (Google·Kakao·Naver·Gemini)',
    );
    await expect(searchInput).toHaveValue('자동 후보 1');
    await page.getByRole('button', { name: '자동 후보 1 상세' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('자동 후보 1', { exact: true })).toBeVisible();
    await dialog.getByRole('button', { name: '후보 삭제' }).click();
    const deleteResponsePromise = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname ===
          '/api/v1/destinations/candidates/1' &&
        response.request().method() === 'DELETE',
    );
    await dialog.getByRole('button', { name: '삭제', exact: true }).click();

    const deleteResponse = await deleteResponsePromise;
    expect(deleteResponse.status()).toBe(404);
    expect(await deleteResponse.json()).toEqual({
      detail: 'candidate not found',
    });
    await expect.poll(() => requests.deleteCandidateIds).toEqual([1]);
    await expect
      .poll(() =>
        requests.detailResponses
          .filter(({ candidateId }) => candidateId === 1)
          .at(-1),
      )
      .toEqual({ candidateId: 1, status: 404, matchStatus: null });
    await expect(dialog).toBeHidden();
    await expect(searchInput).toHaveValue('자동 후보 2');
    await expect(
      page.getByRole('row', { name: /자동 후보 1(?!\d)/ }),
    ).toHaveCount(0);

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('oldest page를 append하고 정확한 새 후보 배너에서 새 snapshot을 시작한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const mainListRequests: URL[] = [];
    const cursorRequests: URL[] = [];
    const newerProbeRequests: URL[] = [];
    let freshSnapshot = false;
    const firstPageCandidates = Array.from({ length: 300 }, (_, index) =>
      reviewCandidateFixture(index + 1, `표식 오래된 후보 ${index + 1}`),
    );
    const oldTail = reviewCandidateFixture(301, '표식 오래된 후보 301');
    const newTail = reviewCandidateFixture(302, '표식 새 후보 302');

    await page.route('**/api/v1/destinations/unmatched**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname !== '/api/v1/destinations/unmatched') {
        await route.continue();
        return;
      }
      const cursor = url.searchParams.get('cursor');
      const newerThanId = url.searchParams.get('newer_than_id');
      const isNewProbe = newerThanId !== null;
      const expectedLimit = isNewProbe ? '1' : '300';
      const contractMismatch =
        url.searchParams.get('limit') !== expectedLimit ||
        url.searchParams.get('q') !== '표식' ||
        url.searchParams.get('sort') !== 'oldest' ||
        url.searchParams.get('is_domestic') !== 'true' ||
        url.searchParams.get('status') !== 'needs_review' ||
        url.searchParams.get('channel_id') !== null ||
        url.searchParams.get('playlist_id') !== null ||
        url.searchParams.get('keyword') !== null ||
        url.searchParams.get('reason') !== null ||
        url.searchParams.get('source_kind') !== null ||
        url.searchParams.get('grounding') !== 'verified_raw' ||
        (isNewProbe && cursor !== null);
      if (contractMismatch) {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ detail: `검수 목록 계약 불일치: ${url.search}` }),
        });
        return;
      }
      if (isNewProbe) {
        newerProbeRequests.push(url);
      } else {
        mainListRequests.push(url);
        if (cursor !== null) cursorRequests.push(url);
      }

      let envelope: ReturnType<typeof reviewQueueEnvelope>;
      if (isNewProbe) {
        if (newerThanId !== '301' && newerThanId !== '302') {
          await route.fulfill({
            status: 400,
            contentType: 'application/json',
            body: JSON.stringify({ detail: `예상하지 않은 baseline: ${newerThanId}` }),
          });
          return;
        }
        envelope = reviewQueueEnvelope([firstPageCandidates[0]], null, {
          total: 302,
          newestId: 302,
          newerThan: newerThanId === '301' ? 1 : 0,
        });
      } else if (!freshSnapshot && cursor === null) {
        envelope = reviewQueueEnvelope(firstPageCandidates, 'old-snapshot-next', {
          total: 301,
          newestId: 301,
          newerThan: 0,
        });
      } else if (!freshSnapshot && cursor === 'old-snapshot-next') {
        envelope = reviewQueueEnvelope([oldTail], null, {
          total: 301,
          newestId: 301,
          newerThan: 0,
        });
      } else if (freshSnapshot && cursor === null) {
        envelope = reviewQueueEnvelope(firstPageCandidates, 'fresh-snapshot-next', {
          total: 302,
          newestId: 302,
          newerThan: 0,
        });
      } else if (freshSnapshot && cursor === 'fresh-snapshot-next') {
        envelope = reviewQueueEnvelope([oldTail, newTail], null, {
          total: 302,
          newestId: 302,
          newerThan: 0,
        });
      } else {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ detail: `예상하지 않은 cursor: ${cursor}` }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(envelope),
      });
    });

    await loginAsAdminWithQuery(
      page,
      '/review?sort=oldest&q=%ED%91%9C%EC%8B%9D&is_domestic=true&grounding=verified_raw',
    );

    await expect(
      page.getByRole('combobox', { name: '원문 근거 필터' }),
    ).toContainText('원문 근거 확인');
    await expect(page.getByRole('textbox', { name: '검수 후보 검색' })).toHaveValue(
      '표식',
    );
    await expect(
      page.getByRole('row', { name: /표식 오래된 후보 1(?!\d)/ }),
    ).toBeVisible();
    await expect(page.getByRole('row', { name: /표식 오래된 후보 300/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /새 후보 1건/ })).toBeVisible();
    await expect
      .poll(() =>
        newerProbeRequests.some(
          (url) => url.searchParams.get('newer_than_id') === '301',
        ),
      )
      .toBe(true);

    await page.getByRole('button', { name: '후보 더 불러오기' }).click();
    await expect(page.getByRole('row', { name: /표식 오래된 후보 301/ })).toBeVisible();
    expect(
      cursorRequests.some(
        (url) => url.searchParams.get('cursor') === 'old-snapshot-next',
      ),
    ).toBe(true);

    freshSnapshot = true;
    await page.getByRole('button', { name: /새 후보 1건/ }).click();
    await expect(page.getByText('300/302개 불러옴')).toBeVisible();
    await expect(page.getByRole('button', { name: /새 후보 1건/ })).toHaveCount(0);
    await expect
      .poll(() =>
        newerProbeRequests.some(
          (url) => url.searchParams.get('newer_than_id') === '302',
        ),
      )
      .toBe(true);
    await page.getByRole('button', { name: '후보 더 불러오기' }).click();
    await expect(page.getByRole('row', { name: /표식 새 후보 302/ })).toBeVisible();
    expect(
      cursorRequests.some(
        (url) => url.searchParams.get('cursor') === 'fresh-snapshot-next',
      ),
    ).toBe(true);
    expect(
      mainListRequests.every(
        (url) =>
          url.searchParams.get('newer_than_id') === null &&
          url.searchParams.get('limit') === '300' &&
          url.searchParams.get('grounding') === 'verified_raw',
      ),
    ).toBe(true);
    expect(
      newerProbeRequests.every(
        (url) =>
          url.searchParams.get('newer_than_id') !== null &&
          url.searchParams.get('limit') === '1' &&
          url.searchParams.get('grounding') === 'verified_raw',
      ),
    ).toBe(true);

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('page 밖 딥링크를 단건 조회하고 URL 필터 포함·이탈을 정확히 안내한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const mainListRequests: URL[] = [];
    const cursorRequests: URL[] = [];
    const newerProbeRequests: URL[] = [];
    const detailRequests: string[] = [];
    const searchQueries: string[] = [];
    const linked = reviewCandidateFixture(
      999,
      '필터검색 page 밖 후보',
      true,
      '00:10',
      'unverified',
    );
    const firstPageCandidates = Array.from({ length: 300 }, (_, index) =>
      reviewCandidateFixture(
        index + 1,
        index === 0
          ? '필터검색 첫 page 후보'
          : `필터검색 page 후보 ${index + 1}`,
        true,
        '00:10',
        'unverified',
      ),
    );

    await page.route('**/api/v1/destinations/unmatched**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname !== '/api/v1/destinations/unmatched') {
        await route.continue();
        return;
      }
      const cursor = url.searchParams.get('cursor');
      const newerThanId = url.searchParams.get('newer_than_id');
      const isNewProbe = newerThanId !== null;
      const query = url.searchParams.get('q');
      const channelId = url.searchParams.get('channel_id');
      const grounding = url.searchParams.get('grounding');
      const isInitialFilter =
        query === '필터검색' &&
        channelId === 'channel-filter' &&
        grounding === 'unverified';
      const isChangedFilter =
        query === '부산' &&
        channelId === 'channel-filter' &&
        grounding === 'unverified';
      const isClearedFilter =
        query === null && channelId === null && grounding === null;
      const contractMismatch =
        url.searchParams.get('limit') !== (isNewProbe ? '1' : '300') ||
        url.searchParams.get('sort') !== 'oldest' ||
        url.searchParams.get('status') !== 'needs_review' ||
        url.searchParams.get('is_domestic') !== null ||
        url.searchParams.get('playlist_id') !== null ||
        url.searchParams.get('keyword') !== null ||
        url.searchParams.get('reason') !== null ||
        url.searchParams.get('source_kind') !== null ||
        (!isInitialFilter && !isChangedFilter && !isClearedFilter) ||
        (isNewProbe && cursor !== null);
      if (contractMismatch) {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ detail: `딥링크 목록 계약 불일치: ${url.search}` }),
        });
        return;
      }
      if (isNewProbe) {
        newerProbeRequests.push(url);
      } else {
        mainListRequests.push(url);
        if (cursor !== null) cursorRequests.push(url);
      }
      let envelope: ReturnType<typeof reviewQueueEnvelope>;
      if (isNewProbe) {
        const expectedBaseline = isChangedFilter ? '0' : '999';
        if (newerThanId !== expectedBaseline) {
          await route.fulfill({
            status: 400,
            contentType: 'application/json',
            body: JSON.stringify({
              detail: `딥링크 probe baseline 불일치: ${newerThanId}`,
            }),
          });
          return;
        }
        envelope = isChangedFilter
          ? reviewQueueEnvelope([], null, {
              total: 0,
              newestId: null,
              newerThan: 0,
            })
          : reviewQueueEnvelope([firstPageCandidates[0]], null, {
              total: 301,
              newestId: 999,
              newerThan: 0,
            });
      } else if (isChangedFilter && cursor === null) {
        envelope = reviewQueueEnvelope([], null, {
          total: 0,
          newestId: null,
          newerThan: 0,
        });
      } else if ((isInitialFilter || isClearedFilter) && cursor === null) {
        envelope = reviewQueueEnvelope(firstPageCandidates, 'must-not-follow', {
          total: 301,
          newestId: 999,
          newerThan: 0,
        });
      } else if (
        (isInitialFilter || isClearedFilter) &&
        cursor === 'must-not-follow'
      ) {
        envelope = reviewQueueEnvelope([linked], null, {
          total: 301,
          newestId: 999,
          newerThan: 0,
        });
      } else {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ detail: `예상하지 않은 cursor: ${cursor}` }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(envelope),
      });
    });
    await page.route(
      '**/api/v1/destinations/candidates/999/detail',
      async (route) => {
        detailRequests.push(route.request().url());
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(
            reviewCandidateDetailFixture(linked, {
              sourceChannelId: 'channel-filter',
              videoChannelId: 'channel-filter',
            }),
          ),
        });
      },
    );
    await page.route('**/api/v1/place-search?**', async (route) => {
      const query = new URL(route.request().url()).searchParams.get('q') ?? '';
      searchQueries.push(query);
      await route.abort('blockedbyclient');
      throw new Error(`page 밖 딥링크에서 예상하지 않은 자동 장소 검색: ${query}`);
    });

    await loginAsAdminWithQuery(
      page,
      '/review?candidate=999&sort=oldest&group=channel&group_value=channel-filter&q=%ED%95%84%ED%84%B0%EA%B2%80%EC%83%89&grounding=unverified',
    );

    await expect(
      page.getByRole('combobox', { name: '원문 근거 필터' }),
    ).toContainText('원문 근거 불일치');
    await expect(
      page.getByText(
        '현재 필터에는 포함되지만 아직 불러온 페이지 밖 후보입니다. 목록 전체를 순회하지 않고 단건 상세로 바로 열었습니다.',
      ),
    ).toBeVisible();
    await expect(
      page.getByPlaceholder('장소명으로 검색 (Google·Kakao·Naver·Gemini)'),
    ).toHaveValue('필터검색 page 밖 후보');
    expect(detailRequests).toHaveLength(1);
    const initialMainRequests = mainListRequests.filter(
      (url) => url.searchParams.get('q') === '필터검색',
    );
    expect(initialMainRequests.length).toBeGreaterThan(0);
    expect(
      initialMainRequests.every(
        (url) =>
          url.searchParams.get('cursor') === null &&
          url.searchParams.get('channel_id') === 'channel-filter' &&
          url.searchParams.get('sort') === 'oldest' &&
          url.searchParams.get('status') === 'needs_review' &&
          url.searchParams.get('grounding') === 'unverified',
      ),
    ).toBe(true);
    expect(
      newerProbeRequests.some(
        (url) =>
          url.searchParams.get('newer_than_id') === '999' &&
          url.searchParams.get('grounding') === 'unverified',
      ),
    ).toBe(true);
    expect(cursorRequests).toEqual([]);
    expect(searchQueries).toEqual([]);
    expect(new URL(page.url()).searchParams.get('candidate')).toBe('999');
    expect(new URL(page.url()).searchParams.get('group_value')).toBe(
      'channel-filter',
    );

    const reviewSearchInput = page.getByRole('textbox', {
      name: '검수 후보 검색',
    });
    await reviewSearchInput.fill('부산');
    const filterOutStatus = page
      .getByRole('status')
      .filter({ hasText: '현재 필터 밖 후보를 단건 상세로 열었습니다.' });
    const loadedOutStatus = page
      .getByRole('status')
      .filter({
        hasText:
          '현재 필터에는 포함되지만 아직 불러온 페이지 밖 후보입니다.',
      });
    const currentDeepLinkFilterState = async () => {
      const latestMainRequest = [...mainListRequests]
        .reverse()
        .find((url) => url.searchParams.get('cursor') === null);
      return {
        urlQuery: new URL(page.url()).searchParams.get('q'),
        urlGrounding: new URL(page.url()).searchParams.get('grounding'),
        inputQuery: await reviewSearchInput.inputValue(),
        latestMainRequest: latestMainRequest
          ? {
              query: latestMainRequest.searchParams.get('q'),
              channelId: latestMainRequest.searchParams.get('channel_id'),
              grounding: latestMainRequest.searchParams.get('grounding'),
            }
          : null,
        filterOutVisible: await filterOutStatus.isVisible(),
        loadedOutCount: await loadedOutStatus.count(),
      };
    };
    const expectedDeepLinkFilterState = {
      urlQuery: '부산',
      urlGrounding: 'unverified',
      inputQuery: '부산',
      latestMainRequest: {
        query: '부산',
        channelId: 'channel-filter',
        grounding: 'unverified',
      },
      filterOutVisible: true,
      loadedOutCount: 0,
    };
    await expect
      .poll(currentDeepLinkFilterState)
      .toEqual(expectedDeepLinkFilterState);
    // debounce 1회 주기 이후에도 늦은 useSearchParams snapshot이 URL/목록/판정을
    // 이전 필터로 되감지 않는지 한 번 더 확인한다.
    await page.waitForTimeout(350);
    expect(await currentDeepLinkFilterState()).toEqual(
      expectedDeepLinkFilterState,
    );
    await filterOutStatus
      .locator('..')
      .getByRole('button', { name: '필터 해제' })
      .click();
    await expect
      .poll(() => new URL(page.url()).searchParams.get('q'))
      .toBeNull();
    expect(new URL(page.url()).searchParams.get('grounding')).toBeNull();
    await expect(
      page.getByRole('combobox', { name: '원문 근거 필터' }),
    ).toContainText('원문 근거 전체');
    expect(new URL(page.url()).searchParams.get('candidate')).toBe('999');
    await expect
      .poll(() =>
        mainListRequests.some(
          (url) =>
            url.searchParams.get('q') === null &&
            url.searchParams.get('channel_id') === null &&
            url.searchParams.get('grounding') === null &&
            url.searchParams.get('cursor') === null,
        ),
      )
      .toBe(true);
    await expect
      .poll(() =>
        newerProbeRequests.some(
          (url) =>
            url.searchParams.get('q') === null &&
            url.searchParams.get('grounding') === null &&
            url.searchParams.get('newer_than_id') === '999',
        ),
      )
      .toBe(true);
    expect(cursorRequests).toEqual([]);
    expect(searchQueries).toEqual([]);

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
        ])) as [
          { items: unknown[] },
          { items: unknown[] },
          unknown[],
        ];

        return `${places.items.length}:${candidates.items.length}:${audits.length}`;
      },
      { timeout: 10_000 },
    )
    .toBe('1:1:1');
}

async function loginAsAdmin(page: Page, nextPath: string) {
  await page.goto(`/login?next=${encodeURIComponent(nextPath)}`);
  await page.locator('#login-username').fill(e2eAdminUsername);
  await page.locator('#login-password').fill(e2eAdminPassword);
  await page.getByRole('button', { name: '로그인' }).click();
  await page.waitForURL((url) => url.pathname === nextPath, { timeout: 10_000 });
}

async function loginAsAdminWithQuery(page: Page, nextPath: string) {
  const expectedURL = new URL(nextPath, 'http://e2e.local');
  await page.goto(`/login?next=${encodeURIComponent(nextPath)}`);
  await page.locator('#login-username').fill(e2eAdminUsername);
  await page.locator('#login-password').fill(e2eAdminPassword);
  await page.getByRole('button', { name: '로그인' }).click();
  await page.waitForURL(
    (url) =>
      url.pathname === expectedURL.pathname && url.search === expectedURL.search,
    { timeout: 10_000 },
  );
}

type ReviewQueueMockFilter = {
  query: string | null;
  channelId: string | null;
  playlistId: string | null;
  keyword: string | null;
  isDomestic: string | null;
  queueReason: string | null;
  sourceKind: string | null;
  grounding: string | null;
};

type ReviewQueueMockGroundingStatus =
  | 'verified_raw'
  | 'unverified'
  | 'missing'
  | 'not_applicable'
  | 'legacy_unknown';

const REVIEW_QUEUE_MOCK_GROUNDING_STATUSES = new Set<string>([
  'verified_raw',
  'unverified',
  'missing',
  'not_applicable',
  'legacy_unknown',
]);

type ReviewQueueMockCursor = {
  version: 1;
  filter: ReviewQueueMockFilter;
  sort: string;
  status: string;
  snapshotId: number;
  lastId: number;
};

const BASE64URL_ALPHABET =
  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

function encodeBase64UrlUtf8(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let encoded = '';
  for (let index = 0; index < bytes.length; index += 3) {
    const remaining = bytes.length - index;
    const chunk =
      (bytes[index] << 16) |
      ((bytes[index + 1] ?? 0) << 8) |
      (bytes[index + 2] ?? 0);
    encoded += BASE64URL_ALPHABET[(chunk >>> 18) & 0x3f];
    encoded += BASE64URL_ALPHABET[(chunk >>> 12) & 0x3f];
    if (remaining > 1) encoded += BASE64URL_ALPHABET[(chunk >>> 6) & 0x3f];
    if (remaining > 2) encoded += BASE64URL_ALPHABET[chunk & 0x3f];
  }
  return encoded;
}

function decodeBase64UrlUtf8(value: string): string {
  if (!value || !/^[A-Za-z0-9_-]+$/.test(value) || value.length % 4 === 1) {
    throw new Error('유효하지 않은 base64url cursor');
  }
  const bytes: number[] = [];
  for (let index = 0; index < value.length; index += 4) {
    const remaining = Math.min(4, value.length - index);
    const digits = [0, 1, 2, 3].map((offset) => {
      if (offset >= remaining) return 0;
      const digit = BASE64URL_ALPHABET.indexOf(value[index + offset]);
      if (digit < 0) throw new Error('유효하지 않은 base64url cursor');
      return digit;
    });
    const chunk =
      (digits[0] << 18) |
      (digits[1] << 12) |
      (digits[2] << 6) |
      digits[3];
    bytes.push((chunk >>> 16) & 0xff);
    if (remaining > 2) bytes.push((chunk >>> 8) & 0xff);
    if (remaining > 3) bytes.push(chunk & 0xff);
  }
  const decoded = new TextDecoder('utf-8', { fatal: true }).decode(
    Uint8Array.from(bytes),
  );
  if (encodeBase64UrlUtf8(decoded) !== value) {
    throw new Error('비정규 base64url cursor');
  }
  return decoded;
}

function reviewQueueMockFilter(url: URL): ReviewQueueMockFilter {
  return {
    query: url.searchParams.get('q'),
    channelId: url.searchParams.get('channel_id'),
    playlistId: url.searchParams.get('playlist_id'),
    keyword: url.searchParams.get('keyword'),
    isDomestic: url.searchParams.get('is_domestic'),
    queueReason: url.searchParams.get('reason'),
    sourceKind: url.searchParams.get('source_kind'),
    grounding: url.searchParams.get('grounding'),
  };
}

function encodeReviewQueueMockCursor(
  url: URL,
  snapshotId: number,
  lastId: number,
): string {
  const payload: ReviewQueueMockCursor = {
    version: 1,
    filter: reviewQueueMockFilter(url),
    sort: url.searchParams.get('sort') ?? '',
    status: url.searchParams.get('status') ?? '',
    snapshotId,
    lastId,
  };
  return encodeBase64UrlUtf8(JSON.stringify(payload));
}

function decodeReviewQueueMockCursor(
  cursor: string,
  url: URL,
): ReviewQueueMockCursor | null {
  try {
    const decoded: unknown = JSON.parse(decodeBase64UrlUtf8(cursor));
    const expectedKeys = [
      'filter',
      'lastId',
      'snapshotId',
      'sort',
      'status',
      'version',
    ];
    if (
      decoded === null ||
      typeof decoded !== 'object' ||
      Array.isArray(decoded)
    ) {
      return null;
    }
    const value = decoded as Record<string, unknown>;
    if (
      Object.keys(value).sort().join(',') !== expectedKeys.join(',') ||
      value.version !== 1 ||
      value.sort !== url.searchParams.get('sort') ||
      value.status !== url.searchParams.get('status') ||
      JSON.stringify(value.filter) !==
        JSON.stringify(reviewQueueMockFilter(url)) ||
      typeof value.snapshotId !== 'number' ||
      !Number.isSafeInteger(value.snapshotId) ||
      value.snapshotId < 0 ||
      typeof value.lastId !== 'number' ||
      !Number.isSafeInteger(value.lastId) ||
      value.lastId < 1 ||
      value.lastId > value.snapshotId
    ) {
      return null;
    }
    return value as unknown as ReviewQueueMockCursor;
  } catch {
    return null;
  }
}

async function installReviewQueueMock(
  page: Page,
  options: {
    initialHiddenOnly?: boolean;
    firstResolveExternallyProcessed?: boolean;
    holdFirstResolveExternallyProcessed?: boolean;
    firstResolveExternallyDeleted?: boolean;
    firstResolveFailsWithoutProcessing?: boolean;
    firstDeleteAlreadySoftDeleted?: boolean;
  } = {},
) {
  const standardDomesticCandidates = Array.from({ length: 301 }, (_, index) =>
    reviewCandidateFixture(
      index + 1,
      `자동 후보 ${index + 1}`,
      true,
      index === 0 ? '12:34-13:00' : '00:10',
    ),
  );
  const standardAllCandidates = [
    ...standardDomesticCandidates,
    reviewCandidateFixture(400, '해외 숨김 후보', false),
  ];
  const initialHiddenCandidates = [
    reviewCandidateFixture(1, '첫 page 해외 후보', false),
    reviewCandidateFixture(5, '뒤 page 국내 후보'),
  ];
  const processedCandidateIds = new Set<number>();
  const resolvedCandidateStatuses = new Map<number, string>();
  const deletedCandidateIds = new Set<number>();
  let releaseHeldResolve: () => void = () => undefined;
  const heldResolveResponse = new Promise<void>((resolve) => {
    releaseHeldResolve = () => resolve();
  });
  const requests = {
    listCursorPayloads: [] as ReviewQueueMockCursor[],
    domesticFilters: [] as Array<string | null>,
    groundingFilters: [] as Array<string | null>,
    mainListRequests: [] as URL[],
    newerProbeRequests: [] as URL[],
    searchQueries: [] as string[],
    resolveBodies: [] as Array<Record<string, unknown>>,
    resolveCandidateIds: [] as number[],
    deleteCandidateIds: [] as number[],
    detailResponses: [] as Array<{
      candidateId: number;
      status: 200 | 404;
      matchStatus: string | null;
    }>,
    processedCandidateIds,
    releaseFirstResolveResponse: () => releaseHeldResolve(),
  };

  await page.route('**/api/v1/destinations/unmatched**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === '/api/v1/destinations/unmatched') {
      try {
      const cursor = url.searchParams.get('cursor');
      const domestic = url.searchParams.get('is_domestic');
      const grounding = url.searchParams.get('grounding');
      const newerThanId = url.searchParams.get('newer_than_id');
      const isNewProbe = newerThanId !== null;
      const contractMismatch =
        url.searchParams.get('limit') !== (isNewProbe ? '1' : '300') ||
        url.searchParams.get('sort') !== 'oldest' ||
        url.searchParams.get('status') !== 'needs_review' ||
        url.searchParams.get('q') !== null ||
        url.searchParams.get('channel_id') !== null ||
        url.searchParams.get('playlist_id') !== null ||
        url.searchParams.get('keyword') !== null ||
        url.searchParams.get('reason') !== null ||
        url.searchParams.get('source_kind') !== null ||
        (grounding !== null &&
          !REVIEW_QUEUE_MOCK_GROUNDING_STATUSES.has(grounding)) ||
        (domestic !== null && domestic !== 'true' && domestic !== 'false') ||
        (isNewProbe && cursor !== null);
      if (contractMismatch) {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ detail: `검수 mock 계약 불일치: ${url.search}` }),
        });
        return;
      }

      const sourceCandidates = options.initialHiddenOnly
        ? initialHiddenCandidates
        : standardAllCandidates;
      const allCandidates = sourceCandidates.filter(
        (candidate) => !processedCandidateIds.has(candidate.id),
      );
      const domesticCandidates =
        domestic === 'true'
          ? allCandidates.filter((candidate) => candidate.is_domestic === true)
          : domestic === 'false'
            ? allCandidates.filter((candidate) => candidate.is_domestic === false)
            : allCandidates;
      const filteredCandidates = domesticCandidates
        .filter(
          (candidate) =>
            grounding === null || candidate.grounding_status === grounding,
        )
        .sort((left, right) => left.id - right.id);
      const newestId = filteredCandidates.at(-1)?.id ?? null;
      let envelope: ReturnType<typeof reviewQueueEnvelope> | null = null;

      if (isNewProbe) {
        requests.newerProbeRequests.push(url);
        const baseline = Number(newerThanId);
        if (
          newerThanId === null ||
          !/^\d+$/.test(newerThanId) ||
          !Number.isSafeInteger(baseline)
        ) {
          await route.fulfill({
            status: 400,
            contentType: 'application/json',
            body: JSON.stringify({
              detail: `유효하지 않은 신규 probe baseline: ${newerThanId}`,
            }),
          });
          return;
        }
        const probeItems = filteredCandidates.slice(0, 1);
        const probeCursor =
          filteredCandidates.length > 1 && newestId != null && probeItems[0]
            ? encodeReviewQueueMockCursor(url, newestId, probeItems[0].id)
            : null;
        envelope = reviewQueueEnvelope(probeItems, probeCursor, {
          total: filteredCandidates.length,
          newestId,
          newerThan: filteredCandidates.filter(
            (candidate) => candidate.id > baseline,
          ).length,
        });
      } else {
        requests.mainListRequests.push(url);
        requests.domesticFilters.push(domestic);
        requests.groundingFilters.push(grounding);
        const decodedCursor =
          cursor === null ? null : decodeReviewQueueMockCursor(cursor, url);
        if (cursor !== null && decodedCursor === null) {
          await route.fulfill({
            status: 400,
            contentType: 'application/json',
            body: JSON.stringify({
              detail: `현재 필터에 사용할 수 없는 cursor: ${cursor}`,
            }),
          });
          return;
        }
        if (decodedCursor) requests.listCursorPayloads.push(decodedCursor);

        const snapshotId = decodedCursor?.snapshotId ?? newestId ?? 0;
        const snapshotCandidates = filteredCandidates.filter(
          (candidate) => candidate.id <= snapshotId,
        );
        const pageCandidates = snapshotCandidates.filter((candidate) =>
          decodedCursor ? candidate.id > decodedCursor.lastId : true,
        );
        const pageItems = pageCandidates.slice(0, 300);
        const lastPageItem = pageItems.at(-1);
        const nextCursor =
          pageCandidates.length > pageItems.length && lastPageItem
            ? encodeReviewQueueMockCursor(url, snapshotId, lastPageItem.id)
            : null;
        envelope = reviewQueueEnvelope(pageItems, nextCursor, {
          total: snapshotCandidates.length,
          newestId: snapshotId || null,
          newerThan: 0,
        });
      }
      if (!envelope) {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ detail: `예상하지 않은 cursor: ${cursor}` }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(envelope),
      });
      return;
      } catch (error) {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: `검수 mock 처리 실패: ${
              error instanceof Error ? error.message : String(error)
            }`,
          }),
        });
        return;
      }
    }

    const resolveMatch = url.pathname.match(
      /^\/api\/v1\/destinations\/unmatched\/(\d+)\/resolve$/,
    );
    if (resolveMatch && request.method() === 'POST') {
      const candidateId = Number(resolveMatch[1]);
      const body = request.postDataJSON() as Record<string, unknown>;
      requests.resolveCandidateIds.push(candidateId);
      requests.resolveBodies.push(body);
      if (
        options.firstResolveFailsWithoutProcessing &&
        requests.resolveCandidateIds.length === 1
      ) {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: '일시적인 resolve 장애' }),
        });
        return;
      }
      if (
        options.firstResolveExternallyDeleted &&
        requests.resolveCandidateIds.length === 1
      ) {
        processedCandidateIds.add(candidateId);
        deletedCandidateIds.add(candidateId);
        resolvedCandidateStatuses.delete(candidateId);
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: '다른 검수자가 후보를 먼저 삭제했습니다.',
          }),
        });
        return;
      }
      resolvedCandidateStatuses.set(
        candidateId,
        body.action === 'ignore' ? 'ignored' : 'user_corrected',
      );
      processedCandidateIds.add(candidateId);
      if (
        options.firstResolveExternallyProcessed &&
        requests.resolveCandidateIds.length === 1
      ) {
        if (options.holdFirstResolveExternallyProcessed) {
          await heldResolveResponse;
        }
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: '다른 검수자가 후보를 먼저 처리했습니다.',
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'resolved' }),
      });
      return;
    }

    await route.continue();
  });

  await page.route('**/api/v1/destinations/candidates/*', async (route) => {
    const request = route.request();
    const deleteMatch = new URL(request.url()).pathname.match(
      /^\/api\/v1\/destinations\/candidates\/(\d+)$/,
    );
    if (deleteMatch && request.method() === 'DELETE') {
      const candidateId = Number(deleteMatch[1]);
      requests.deleteCandidateIds.push(candidateId);
      processedCandidateIds.add(candidateId);
      deletedCandidateIds.add(candidateId);
      resolvedCandidateStatuses.delete(candidateId);
      if (
        options.firstDeleteAlreadySoftDeleted &&
        requests.deleteCandidateIds.length === 1
      ) {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: 'candidate not found',
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ deleted: true, id: candidateId }),
      });
      return;
    }
    await route.continue();
  });

  await page.route(
    '**/api/v1/destinations/candidates/*/detail',
    async (route) => {
      const detailMatch = new URL(route.request().url()).pathname.match(
        /^\/api\/v1\/destinations\/candidates\/(\d+)\/detail$/,
      );
      if (!detailMatch) {
        await route.continue();
        return;
      }
      const candidateId = Number(detailMatch[1]);
      const sourceCandidates = options.initialHiddenOnly
        ? initialHiddenCandidates
        : standardAllCandidates;
      const candidate = sourceCandidates.find((item) => item.id === candidateId);
      if (!candidate || deletedCandidateIds.has(candidateId)) {
        requests.detailResponses.push({
          candidateId,
          status: 404,
          matchStatus: null,
        });
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'candidate not found' }),
        });
        return;
      }
      const matchStatus = resolvedCandidateStatuses.get(candidateId);
      const latestCandidate = matchStatus
        ? { ...candidate, match_status: matchStatus }
        : candidate;
      requests.detailResponses.push({
        candidateId,
        status: 200,
        matchStatus: latestCandidate.match_status,
      });
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(reviewCandidateDetailFixture(latestCandidate)),
      });
    },
  );

  await page.route('**/api/v1/place-search?**', async (route) => {
    const query = new URL(route.request().url()).searchParams.get('q') ?? '';
    requests.searchQueries.push(query);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(reviewSearchResult(query)),
    });
  });

  return requests;
}

function reviewQueueEnvelope(
  items: ReturnType<typeof reviewCandidateFixture>[],
  nextCursor: string | null,
  metadata: {
    total: number;
    newestId: number | null;
    newerThan: number;
  },
) {
  return {
    items,
    next_cursor: nextCursor,
    has_more: nextCursor !== null,
    total: metadata.total,
    newest_id: metadata.newestId,
    newer_than: metadata.newerThan,
  };
}

function reviewCandidateFixture(
  id: number,
  name: string,
  isDomestic = true,
  timestampStart = '00:10',
  groundingStatus: ReviewQueueMockGroundingStatus = 'verified_raw',
) {
  return {
    id,
    video_id: `review-video-${id}`,
    video_title: `자동 검수 영상 ${id}`,
    channel_title: '자동 검수 채널',
    ai_place_name: name,
    location_hint: null,
    candidate_category: '카페',
    candidate_category_code: '0',
    match_status: 'needs_review',
    confidence_score: id === 1 ? 0.83 : null,
    source_kind: 'transcript',
    grounding_status: groundingStatus,
    created_at: '2026-07-13T03:00:00Z',
    queue_reason: isDomestic ? 'extraction_only' : 'foreign',
    timestamp_start: timestampStart,
    is_domestic: isDomestic,
  };
}

function reviewCandidateDetailFixture(
  listItem: ReturnType<typeof reviewCandidateFixture>,
  provenance: {
    sourceChannelId?: string | null;
    sourcePlaylistId?: string | null;
    videoChannelId?: string | null;
    sourceSearchQuery?: string | null;
  } = {},
) {
  return {
    list_item: listItem,
    candidate: {
      id: listItem.id,
      video_id: listItem.video_id,
      source_channel_id: provenance.sourceChannelId ?? null,
      source_playlist_id: provenance.sourcePlaylistId ?? null,
      ai_place_name: listItem.ai_place_name,
      location_hint: listItem.location_hint,
      candidate_category: listItem.candidate_category,
      candidate_category_code: listItem.candidate_category_code,
      match_status: listItem.match_status,
      confidence_score: listItem.confidence_score,
      is_domestic: listItem.is_domestic,
      speaker_note: null,
      source_kind: listItem.source_kind,
      grounding_status: listItem.grounding_status,
      feature_export_status: 'pending',
      timestamp_start: listItem.timestamp_start,
      timestamp_end: null,
      source_text: null,
    },
    video: {
      video_id: listItem.video_id,
      title: listItem.video_title,
      url: `https://www.youtube.com/watch?v=${listItem.video_id}`,
      channel_id: provenance.videoChannelId ?? null,
      channel_title: listItem.channel_title,
      source_search_query: provenance.sourceSearchQuery ?? null,
      published_at: null,
      duration_seconds: null,
      description: null,
    },
    source_run: null,
    provider_evidence: null,
    sibling_candidates: [],
  };
}

function reviewSearchResult(query: string) {
  return {
    query,
    searched_at: '2026-07-13T03:00:00Z',
    google: [],
    kakao: [
      {
        provider: 'kakao',
        native_id: `review-${query}`,
        name: `검색 결과 ${query}`,
        address: `테스트 주소 ${query}`,
        road_address: null,
        latitude: 33.45,
        longitude: 126.55,
        category: null,
        storage_allowed: true,
        storage_block_reason: null,
      },
    ],
    naver: [],
    errors: {},
  };
}

async function installDestinationPaginationMock(
  page: Page,
  detail?: ReturnType<typeof destinationDetailFixture>,
) {
  const requests = { list: [] as string[], detail: [] as string[] };

  await page.route('**/api/v1/destinations**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/destinations') {
      requests.list.push(url.toString());
      const cursor = url.searchParams.get('cursor');
      const pageNumber = cursor === null ? 1 : Number(cursor.replace('page-', ''));
      if (Number.isInteger(pageNumber) && pageNumber >= 1 && pageNumber <= 6) {
        const placeIds = destinationPageIds(pageNumber);
        const items = placeIds.map((placeId) =>
          destinationListFixture(
            placeId,
            pageNumber === 2 && placeId === 100
              ? '갱신된 페이지 장소 100'
              : undefined,
          ),
        );
        const nextCursor = pageNumber < 6 ? `page-${pageNumber + 1}` : null;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(destinationEnvelope(items, nextCursor)),
        });
        return;
      }
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `예상하지 않은 cursor: ${cursor}` }),
      });
      return;
    }

    if (detail && url.pathname === '/api/v1/destinations/501/detail') {
      requests.detail.push(url.toString());
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(detail),
      });
      return;
    }

    await route.continue();
  });

  return requests;
}

async function loadMoreDestinationPage(
  page: Page,
  placesRegion: Locator,
  cursor: string,
) {
  const nextPageRequest = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return (
      url.pathname === '/api/v1/destinations' &&
      url.searchParams.get('cursor') === cursor
    );
  });
  await placesRegion.getByRole('button', { name: '장소 더 불러오기' }).click();
  const requestURL = new URL((await nextPageRequest).url());
  expect(requestURL.searchParams.get('limit')).toBe('100');
  expect(requestURL.searchParams.get('cursor')).toBe(cursor);
}

function destinationEnvelope(
  items: ReturnType<typeof destinationListFixture>[],
  nextCursor: string | null = null,
) {
  return {
    items,
    next_cursor: nextCursor,
    has_more: nextCursor !== null,
    total: 501,
    newest_id: 501,
    newer_than: 0,
  };
}

function destinationPageIds(pageNumber: number): number[] {
  if (pageNumber === 1) return Array.from({ length: 100 }, (_, index) => index + 1);
  if (pageNumber === 2) {
    return [100, ...Array.from({ length: 99 }, (_, index) => index + 101)];
  }
  const startPlaceId = (pageNumber - 1) * 100;
  const endPlaceId = pageNumber === 6 ? 501 : startPlaceId + 99;
  return Array.from(
    { length: endPlaceId - startPlaceId + 1 },
    (_, index) => startPlaceId + index,
  );
}

function destinationListFixture(placeId: number, name?: string) {
  return {
    place_id: placeId,
    name: name ?? `페이지 장소 ${placeId}`,
    description: null,
    gemini_enriched_description: null,
    latitude: 33 + placeId / 10_000,
    longitude: 126 + placeId / 10_000,
    category: '테스트',
    category_code_suggestion: null,
    sigungu_code: null,
    sigungu_name: null,
    legal_dong_code: null,
    legal_dong_name: null,
    official_address: `테스트 주소 ${placeId}`,
    road_address: null,
    is_geocoded: true,
    mention_count: 1,
    source_channel_count: 0,
    source_videos: [],
  };
}

function destinationDetailFixture(placeId: number) {
  return {
    place: {
      place_id: placeId,
      name: `페이지 밖 장소 ${placeId}`,
      category: '테스트',
      category_code_suggestion: null,
      sigungu_code: null,
      sigungu_name: null,
      legal_dong_code: null,
      legal_dong_name: null,
      official_address: `페이지 밖 테스트 주소 ${placeId}`,
      road_address: null,
      latitude: 33.501,
      longitude: 126.501,
      is_geocoded: true,
      description: null,
      gemini_enriched_description: null,
      detailed_research_content: null,
    },
    stats: { mention_count: 1, video_count: 0, channel_count: 0 },
    source_videos: [],
  };
}

function resolvePython() {
  if (process.env.KTC_E2E_PYTHON) {
    return process.env.KTC_E2E_PYTHON;
  }
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

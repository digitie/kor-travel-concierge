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
    await loginAsAdmin(page, '/collect');

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

    // 수집 폼 성공 안내(작업 링크 포함)와 진행 중 작업 패널 표시를 확인한다.
    await expect(page.getByText('수집 작업을 등록했습니다')).toBeVisible();
    await expect(
      page.getByRole('link', { name: '진행 상황 보기' }),
    ).toHaveAttribute('href', `/jobs/${job.job_id}`);

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

  test('저장·제외·개별 삭제 뒤 visible 다음 후보를 검색하고 마지막 page에서 완료한다', async ({
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
      await expect(page.getByRole('row', { name: new RegExp(name) })).toBeVisible();
    }
    await page.waitForTimeout(250);
    expect(requests.searchQueries).toEqual([]);

    await expect(page.getByRole('link', { name: /영상 보기/ })).toHaveAttribute(
      'href',
      'https://www.youtube.com/watch?v=review-video-1&t=754s',
    );

    const hideForeign = page.getByRole('switch', {
      name: '해외(국내 아님) 후보 숨기기',
    });
    await hideForeign.click();
    await expect(hideForeign).toBeChecked();
    await expect(searchInput).toHaveValue('자동 후보 1');

    const firstRow = page.getByRole('row', { name: /자동 후보 1/ });
    await expect(firstRow).toHaveAttribute('aria-selected', 'true');
    await firstRow.click();
    await expect.poll(() => requests.searchQueries).toContain('자동 후보 1');
    await page
      .getByRole('button', { name: /^검색 결과 자동 후보 1/ })
      .click();
    await page.getByRole('button', { name: '저장', exact: true }).click();

    await expect.poll(() => requests.resolveBodies.length).toBe(1);
    expect(requests.resolveBodies[0]).toMatchObject({ action: 'create_place' });
    await expect(searchInput).toHaveValue('자동 후보 2');
    await expect(page.getByRole('row', { name: /자동 후보 2/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect.poll(() => requests.searchQueries).toContain('자동 후보 2');

    await page.getByRole('button', { name: '제외', exact: true }).click();
    await expect.poll(() => requests.resolveBodies.length).toBe(2);
    expect(requests.resolveBodies[1]).toMatchObject({ action: 'ignore' });
    await expect(searchInput).toHaveValue('자동 후보 3');
    await expect(page.getByRole('row', { name: /자동 후보 3/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect.poll(() => requests.searchQueries).toContain('자동 후보 3');

    await page
      .getByRole('button', { name: '자동 후보 3 후보 삭제', exact: true })
      .click();
    await page.getByRole('button', { name: '삭제', exact: true }).click();
    await expect.poll(() => requests.deleteCandidateIds).toEqual([3]);

    await expect.poll(() => requests.listCursors).toContain('review-page-2');
    await expect.poll(() => requests.listCursors).toContain('review-page-3');
    await expect(searchInput).toHaveValue('자동 후보 4');
    await expect.poll(() => requests.searchQueries).toContain('자동 후보 4');
    await expect(
      page.getByRole('row', { name: /해외 숨김 후보/ }),
    ).toHaveCount(0);

    await page.getByRole('button', { name: '제외', exact: true }).click();
    await expect.poll(() => requests.resolveBodies.length).toBe(3);
    expect(requests.resolveBodies.map((body) => body.action)).toEqual([
      'create_place',
      'ignore',
      'ignore',
    ]);
    expect(requests.resolveCandidateIds).toEqual([1, 2, 4]);
    await expect(
      page
        .getByRole('status')
        .filter({ hasText: '현재 표시 조건의 검수 후보를 모두 처리했습니다.' })
        .first(),
    ).toBeVisible();

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('첫 page가 숨김 후보뿐이면 국내 후보가 나올 때까지 자동 탐색한다', async ({
    page,
  }) => {
    const errors = collectConsoleErrors(page);
    const requests = await installReviewQueueMock(page, {
      initialHiddenOnly: true,
    });

    await loginAsAdmin(page, '/review');

    const hideForeign = page.getByRole('switch', {
      name: '해외(국내 아님) 후보 숨기기',
    });
    await hideForeign.click();
    await expect(hideForeign).toBeChecked();
    await expect.poll(() => requests.listCursors).toContain(
      'review-initial-page-2',
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

async function installReviewQueueMock(
  page: Page,
  options: { initialHiddenOnly?: boolean } = {},
) {
  const requests = {
    listCursors: [] as Array<string | null>,
    searchQueries: [] as string[],
    resolveBodies: [] as Array<Record<string, unknown>>,
    resolveCandidateIds: [] as number[],
    deleteCandidateIds: [] as number[],
  };

  await page.route('**/api/v1/destinations/unmatched**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === '/api/v1/destinations/unmatched') {
      const cursor = url.searchParams.get('cursor');
      requests.listCursors.push(cursor);
      const envelope = options.initialHiddenOnly
        ? cursor === null
          ? reviewQueueEnvelope(
              [reviewCandidateFixture(91, '첫 page 해외 후보', false)],
              'review-initial-page-2',
            )
          : cursor === 'review-initial-page-2'
            ? reviewQueueEnvelope([
                reviewCandidateFixture(5, '뒤 page 국내 후보'),
              ])
            : null
        : cursor === null
          ? reviewQueueEnvelope(
              [
                reviewCandidateFixture(1, '자동 후보 1', true, '12:34-13:00'),
                reviewCandidateFixture(2, '자동 후보 2'),
                reviewCandidateFixture(3, '자동 후보 3'),
              ],
              'review-page-2',
            )
          : cursor === 'review-page-2'
            ? reviewQueueEnvelope(
                [reviewCandidateFixture(90, '해외 숨김 후보', false)],
                'review-page-3',
              )
            : cursor === 'review-page-3'
              ? reviewQueueEnvelope([reviewCandidateFixture(4, '자동 후보 4')])
              : null;
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
    }

    const resolveMatch = url.pathname.match(
      /^\/api\/v1\/destinations\/unmatched\/(\d+)\/resolve$/,
    );
    if (resolveMatch && request.method() === 'POST') {
      requests.resolveCandidateIds.push(Number(resolveMatch[1]));
      requests.resolveBodies.push(
        request.postDataJSON() as Record<string, unknown>,
      );
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
      requests.deleteCandidateIds.push(Number(deleteMatch[1]));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ deleted: true, id: Number(deleteMatch[1]) }),
      });
      return;
    }
    await route.continue();
  });

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
  nextCursor: string | null = null,
) {
  return {
    items,
    next_cursor: nextCursor,
    has_more: nextCursor !== null,
    total: 5,
    newest_id: 90,
    newer_than: 0,
  };
}

function reviewCandidateFixture(
  id: number,
  name: string,
  isDomestic = true,
  timestampStart = '00:10',
) {
  return {
    id,
    video_id: `review-video-${id}`,
    ai_place_name: name,
    location_hint: null,
    candidate_category: '카페',
    candidate_category_code: '0',
    match_status: 'needs_review',
    timestamp_start: timestampStart,
    is_domestic: isDomestic,
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

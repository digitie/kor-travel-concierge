import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

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

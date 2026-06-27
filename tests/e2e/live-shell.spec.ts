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
    await expect(page.getByRole('heading', { name: '작업 테이블' })).toBeVisible();
    await expect(page.getByRole('tab', { name: /진행 중/ })).toBeVisible();
    await expect(page.getByRole('tab', { name: /완료 이력/ })).toBeVisible();
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
    const queueRegion = page.getByRole('region', { name: '진행 중 작업' });
    await expect(queueRegion).toBeVisible();
    await expect(queueRegion.getByText('진행 중 작업')).toBeVisible();
    await expect(page.getByText('기본 카테고리').first()).toBeVisible();
    await expect(page.getByLabel('기본 카테고리').first()).toBeVisible();

    const jobsRegion = page.getByRole('region', { name: '반복 작업' });
    await expect(jobsRegion.getByRole('heading', { name: '반복 작업' })).toBeVisible();
    await expect(jobsRegion.getByRole('columnheader', { name: '대상' }).first()).toBeVisible();
    await expect(jobsRegion.getByRole('columnheader', { name: '주기' })).toBeVisible();
    await expect(jobsRegion.getByRole('columnheader', { name: '기본' })).toBeVisible();
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
    await expect(dialog.getByText('기본 카테고리').first()).toBeVisible();
    await expect(dialog.locator('#recurring-edit-interval')).toBeVisible();
    await expect(dialog.locator('#recurring-edit-count')).toBeVisible();
    await expect(dialog.locator('#recurring-edit-max-videos')).toBeVisible();
    await expect(dialog.locator('#recurring-edit-category')).toBeVisible();
    await expect(dialog.getByText('강제 다운로드 (전체 재수집)')).toBeVisible();
    await expect(dialog.getByText('저장 직후 한 번만 전체 재수집 작업을 실행합니다.')).toBeVisible();
    await dialog.getByRole('button', { name: '닫기' }).first().click();

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('검수 큐 테이블, 3분할 작업면, 상세 다이얼로그가 동작한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await loginAsAdmin(page, '/review');

    await expect(page.getByRole('heading', { name: '검수 큐', exact: true })).toBeVisible();
    await expect(page.getByText('검수 대기 후보')).toBeVisible();

    try {
      await expect
        .poll(() => page.locator('tbody tr').count(), { timeout: 15_000 })
        .toBeGreaterThan(0);
    } catch {
      test.skip(true, 'n150 검수 대기 후보가 없으면 후보 상세 UI 검증을 건너뛴다.');
    }
    const firstRow = page.locator('tbody tr').first();

    await expect(page.getByRole('columnheader', { name: '후보', exact: true })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: '출처', exact: true })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: '상태', exact: true })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: '액션', exact: true })).toBeVisible();

    await firstRow.locator('input[type="checkbox"]').check();
    await expect(page.getByText('후보 1개 선택됨')).toBeVisible();
    await expect(page.getByRole('button', { name: '선택 삭제' })).toBeVisible();
    await page.getByRole('button', { name: '선택 해제' }).click();
    await expect(page.getByText('후보 1개 선택됨')).toHaveCount(0);

    await firstRow.locator('td').nth(1).locator('button').click();
    await expect(page.getByRole('button', { name: '검색', exact: true })).toBeVisible();
    await expect(page.getByText('확정 정보')).toBeVisible();
    await expect(page.getByText('Google Places', { exact: true })).toBeVisible();
    await expect(page.getByText('Kakao', { exact: true })).toBeVisible();
    await expect(page.getByText('Naver', { exact: true })).toBeVisible();
    await expect(page.locator('.maplibregl-map')).toBeVisible();

    await page.getByRole('button', { name: /상세 보기/ }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: '검수 후보 상세' })).toBeVisible();
    await expect(dialog.getByRole('heading', { name: '동영상', exact: true })).toBeVisible();
    await expect(dialog.getByRole('heading', { name: '동영상 내 근거(어디에 나왔는지)' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: '근거 위치로 이동' })).toBeVisible();

    const rawTab = dialog.getByRole('tab', { name: '타임스탬프 포함' });
    if (await rawTab.isVisible().catch(() => false)) {
      await expect(dialog.getByRole('tab', { name: '정리본' })).toBeVisible();
      await dialog.getByRole('tab', { name: '정리본' }).click();
      await expect(dialog.getByRole('tabpanel', { name: '정리본' })).toBeVisible();
      await dialog.getByRole('tab', { name: '타임스탬프 포함' }).click();
    } else {
      await expect(dialog.getByText(/보정 자막 없음|불러오는 중/)).toBeVisible();
    }

    await dialog.getByRole('button', { name: '닫기' }).click();

    const seededRow = page.locator('tbody tr').filter({ hasText: 'KTC Live E2E 검수 후보' });
    if ((await seededRow.count()) > 0) {
      await seededRow.first().locator('input[type="checkbox"]').check();
      page.once('dialog', (confirmDialog) => confirmDialog.accept());
      await page.getByRole('button', { name: '선택 삭제' }).click();
      await expect(seededRow).toHaveCount(0);
    }

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('결과 필터와 출처 동영상 상세 확장이 동작한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await loginAsAdmin(page, '/');

    await expect(page.getByRole('heading', { name: '결과', exact: true })).toBeVisible();
    await expect(page.getByLabel('장소 글자 검색')).toBeVisible();
    await expect(page.getByLabel('카테고리 필터')).toBeVisible();
    await expect(page.getByLabel('시군구 필터')).toBeVisible();

    const placeList = page.locator('section[aria-label="장소 목록"]');
    try {
      await expect
        .poll(() => placeList.getByRole('button', { name: /상세/ }).count(), {
          timeout: 15_000,
        })
        .toBeGreaterThan(0);
    } catch {
      test.skip(true, 'n150 결과 장소가 없으면 장소 상세 UI 검증을 건너뛴다.');
    }

    await placeList.getByRole('button', { name: /상세/ }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: '장소 상세' })).toBeVisible();
    await expect(dialog.getByRole('heading', { name: /출처 동영상/ })).toBeVisible();

    const sourceVideoButton = dialog.getByRole('button', {
      name: /출처 동영상 상세/,
    }).first();
    try {
      await expect(sourceVideoButton).toBeVisible({ timeout: 5_000 });
    } catch {
      test.skip(true, '출처 동영상이 없는 장소면 영상 상세 확장 검증을 건너뛴다.');
    }
    await sourceVideoButton.click();
    await expect(dialog.getByRole('heading', { name: '출처 동영상 상세' })).toBeVisible();
    await expect(dialog.getByRole('link', { name: /YouTube/ })).toBeVisible();
    await expect(dialog.getByRole('button', { name: '근거 위치로 이동' })).toBeVisible();

    const rawTab = dialog.getByRole('tab', { name: '타임스탬프 포함' });
    if (await rawTab.isVisible().catch(() => false)) {
      await dialog.getByRole('tab', { name: '정리본' }).click();
      await expect(dialog.getByRole('tabpanel', { name: '정리본' })).toBeVisible();
      await rawTab.click();
    } else {
      await expect(dialog.getByText(/보정 자막 없음|불러오는 중/)).toBeVisible();
    }

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

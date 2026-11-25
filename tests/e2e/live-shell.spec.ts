import { expect, test, type Page } from '@playwright/test';

const liveEnabled = process.env.KTC_LIVE_E2E === '1';
const e2eAdminUsername = process.env.KTC_E2E_ADMIN_USERNAME ?? 'admin';
const e2eAdminPassword = process.env.KTC_E2E_ADMIN_PASSWORD ?? '';
const liveBackendURL = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:12601';

test.describe('n150 live UI 셸 검증', () => {
  test.skip(!liveEnabled, 'KTC_LIVE_E2E=1 일 때만 n150 live UI를 검증한다.');
  // live 데이터(수천 검수 후보)와 실제 provider 검색·지도 타일을 상대하므로
  // 기본 30초로는 검수 큐 시나리오가 빠듯하다.
  test.beforeEach(() => {
    test.setTimeout(60_000);
  });

  test('Prometheus scrape endpoint가 운영 지표를 반환한다', async ({ request }) => {
    const response = await request.get(`${liveBackendURL}/metrics`);
    expect(response.status()).toBe(200);
    const body = await response.text();
    expect(body).toContain('# HELP ktc_http_requests');
    expect(body).toContain('ktc_crawl_run_metrics_refresh_success');
  });

  test('메뉴, 상단 작업 상태, 상태 페이지, 설정 페이지가 동작한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await loginAsAdmin(page, '/');

    await expect(
      page.getByRole('link', { name: 'Travel Concierge Admin UI' }),
    ).toBeVisible();
    await expect(page.getByRole('heading', { name: '개요 - 결과', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: /결과/ }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: /수집/ }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: /검수/ }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: /작업/ }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: /상태/ }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: /설정/ }).first()).toBeVisible();

    // T-192: 헤더 작업 상태 링크는 큐/이력 통합 인덱스(/jobs)로 이동한다.
    const statusLink = page.getByRole('link', { name: /작업 상태/ }).first();
    await expect(statusLink).toBeVisible();
    await statusLink.click();
    await page.waitForURL(/\/jobs(\?|$)/);
    await expect(
      page.getByRole('heading', { name: '수집 파이프라인 - 작업', exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole('heading', { name: '진행 중 · 대기' }),
    ).toBeVisible();
    await expect(page.getByRole('heading', { name: '작업 이력' })).toBeVisible();

    const disposableJobId = await createDisposableTerminalRun(page);
    const runPath = `/api/v1/runs/${disposableJobId}`;
    await page.route(`**${runPath}`, async (route) => {
      const response = await route.fetch();
      const body = (await response.json()) as Record<string, unknown>;
      await route.fulfill({
        response,
        json: {
          ...body,
          state: 'failed',
          current_message: 'YouTube API 호출 중 오류가 발생했습니다.',
          last_error:
            'YouTube API search 호출 실패(status=403; attempts=1; reason=quotaExceeded; api_status=PERMISSION_DENIED; message=KTC live E2E 오류 상세)',
        },
      });
    });
    await page.route(`**${runPath}/video-stats`, async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'KTC live E2E 통계 오류 상세' }),
      });
    });
    await page.route(`**${runPath}/places`, async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'KTC live E2E POI 오류 상세' }),
      });
    });
    let deletedByUI = false;
    try {
      await page.goto(`/jobs/${disposableJobId}`);
      await expect(page.getByRole('heading', { name: '수집 파이프라인 - 작업 상세', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: '뒤로' })).toBeVisible();
      await expect(page.getByRole('heading', { name: '로그와 결과' })).toBeVisible();
      await expect(page.getByRole('heading', { name: '영상 처리' })).toBeVisible();
      await expect(page.getByLabel('오류 상세')).toContainText('KTC live E2E 오류 상세');
      await expect(
        page.getByRole('alert').filter({ hasText: '추출된 POI를 불러오지 못했습니다.' }),
      ).toContainText('KTC live E2E POI 오류 상세');
      await expect(
        page.getByRole('alert').filter({ hasText: '영상 처리 통계를 불러오지 못했습니다.' }),
      ).toContainText('KTC live E2E 통계 오류 상세');

      const deleteButton = page.getByRole('button', { name: '삭제', exact: true });
      await deleteButton.click();
      const deleteDialog = page.getByRole('alertdialog');
      const cancelButton = deleteDialog.getByRole('button', {
        name: '취소',
        exact: true,
      });
      await expect(cancelButton).toBeVisible();
      await cancelButton.click();
      await expect(deleteDialog).toHaveCount(0);

      await deleteButton.click();
      await deleteDialog.getByRole('button', { name: '삭제', exact: true }).click();
      await page.waitForURL(/\/jobs\?deleted=/);
      await expect(page.getByRole('status')).toContainText(
        `작업 #${disposableJobId}를 삭제했습니다.`,
      );
      deletedByUI = true;
    } finally {
      await page.unroute(`**${runPath}`);
      await page.unroute(`**${runPath}/video-stats`);
      await page.unroute(`**${runPath}/places`);
      if (!deletedByUI) {
        await deleteDisposableRun(page, disposableJobId);
      }
    }

    // /status는 시스템 메트릭·저장소·감사 로그 전용으로 축소됐다.
    await page.getByRole('link', { name: '상태', exact: true }).first().click();
    await page.waitForURL('**/status');
    await expect(page.getByRole('heading', { name: '시스템 - 상태', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: '저장소 상세' })).toBeVisible();

    await page.getByRole('link', { name: /설정/ }).first().click();
    await page.waitForURL('**/settings');
    await expect(page.getByRole('heading', { name: '시스템 - 설정', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'AI 엔진', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'API 키', exact: true })).toBeVisible();
    await expect(
      page.getByRole('heading', { name: '외부 공개 API 키', exact: true }),
    ).toBeVisible();
    await expect(page.locator('#ai-engine-select')).toBeVisible();

    await page.getByRole('link', { name: /검수/ }).first().click();
    await page.waitForURL('**/review');
    await expect(page.getByRole('heading', { name: '검수 - 검수 큐', exact: true })).toBeVisible();

    await page.getByRole('link', { name: /수집/ }).first().click();
    await page.waitForURL('**/collect');
    await expect(page.getByRole('heading', { name: '수집 파이프라인 - 수집', exact: true })).toBeVisible();

    // 외부 공급 API 테스트 페이지: 엔드포인트 선택 → 실행 → 응답 상태 표시.
    await page.getByRole('link', { name: /^API/ }).first().click();
    await page.waitForURL('**/api-test');
    await expect(page.getByRole('heading', { name: '시스템 - API 테스트', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: '요청', exact: true })).toBeVisible();
    await page.getByRole('button', { name: '실행', exact: true }).click();
    await expect(page.getByText(/^HTTP 200$/)).toBeVisible();

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('수집 반복 작업 테이블과 수정 다이얼로그가 누적 정보를 보여준다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await loginAsAdmin(page, '/collect');

    await expect(page.getByRole('heading', { name: '수집 파이프라인 - 수집', exact: true })).toBeVisible();
    const queueRegion = page.getByRole('region', { name: '진행 중 작업' });
    await expect(queueRegion).toBeVisible();
    await expect(queueRegion.getByText('진행 중 작업')).toBeVisible();
    await expect(page.getByText('기본 카테고리').first()).toBeVisible();
    await expect(page.getByLabel('기본 카테고리').first()).toBeVisible();

    const jobsRegion = page.getByRole('region', { name: '반복 작업' });
    await expect(jobsRegion.getByRole('heading', { name: '반복 작업' })).toBeVisible();
    const viewport = page.viewportSize();
    const jobsLayout = await jobsRegion.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const parentBox = element.parentElement?.getBoundingClientRect();
      return {
        bottom: box.bottom,
        width: box.width,
        parentWidth: parentBox?.width ?? box.width,
      };
    });
    expect(jobsLayout.width).toBeGreaterThanOrEqual(jobsLayout.parentWidth - 2);
    if (viewport) {
      expect(jobsLayout.bottom).toBeLessThanOrEqual(viewport.height + 2);
    }
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

    await expect(page.getByRole('heading', { name: '검수 - 검수 큐', exact: true })).toBeVisible();
    const modeGroup = page.getByRole('group', { name: '검수 화면 모드' });
    await modeGroup.getByRole('button', { name: '목록/관리' }).click();
    await expect(
      modeGroup.getByRole('button', { name: '목록/관리' }),
    ).toHaveAttribute('aria-pressed', 'true');
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

    const bulkTools = page.getByRole('region', { name: '일괄 검수 도구' });
    await firstRow.getByRole('checkbox').check();
    await expect(bulkTools.getByRole('status')).toHaveText('현재 후보 1건 선택됨');
    await expect(page.getByRole('button', { name: '선택 삭제' })).toBeVisible();
    await page.getByRole('button', { name: '선택 해제' }).click();
    await expect(bulkTools.getByRole('status')).toHaveText(
      '후보를 선택하면 일괄 처리할 수 있습니다.',
    );

    await firstRow.locator('td').nth(3).click();
    await expect(firstRow).toHaveAttribute('data-state', 'selected');
    await expect(page.getByRole('button', { name: '검색', exact: true })).toBeVisible();
    await expect(page.getByText('확정 정보')).toBeVisible();
    await expect(page.getByText('Google Maps Places', { exact: true })).toBeVisible();
    await expect(page.getByText('Kakao', { exact: true })).toBeVisible();
    await expect(page.getByText('Naver', { exact: true })).toBeVisible();
    await expect(page.locator('.maplibregl-map')).toBeVisible();
    const mapBox = await page.locator('#vworld-map-container').boundingBox();
    expect(mapBox?.height ?? 0).toBeGreaterThan(300);
    expect(mapBox?.height ?? 0).toBeLessThan(1200);
    const candidatePaneBox = await page
      .getByText('검수 대기 후보')
      .locator('xpath=ancestor::aside')
      .boundingBox();
    const viewport = page.viewportSize();
    if (viewport) {
      expect(candidatePaneBox?.height ?? 0).toBeLessThanOrEqual(viewport.height);
    }

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
      await seededRow.first().getByRole('checkbox').check();
      // window.confirm 대신 AlertDialog로 확인한다 (ConfirmActionButton).
      await page.getByRole('button', { name: '선택 삭제' }).click();
      const confirmDialog = page.getByRole('alertdialog');
      await expect(confirmDialog.getByText(/삭제할까요/)).toBeVisible();
      await confirmDialog.getByRole('button', { name: '삭제', exact: true }).click();
      await expect(seededRow).toHaveCount(0);
    }

    expectRelevantConsoleErrors(errors).toEqual([]);
  });

  test('결과 필터와 출처 동영상 상세 확장이 동작한다', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await loginAsAdmin(page, '/');

    await expect(page.getByRole('heading', { name: '개요 - 결과', exact: true })).toBeVisible();
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
    await expect(page.locator('.maplibregl-map')).toBeVisible();
    const resultMapBox = await page.locator('#vworld-map-container').boundingBox();
    expect(resultMapBox?.height ?? 0).toBeGreaterThan(300);
    expect(resultMapBox?.height ?? 0).toBeLessThan(1200);

    const placeRows = placeList.locator('div[data-selected]');
    if ((await placeRows.count()) > 1) {
      // 행의 첫 button은 내보내기 체크박스다. 장소 선택은 aria-pressed 버튼이다.
      await placeRows.nth(1).locator('button[aria-pressed]').click();
      await expect
        .poll(async () => {
          const layout = await page.evaluate(() => {
            const map = document
              .querySelector('#vworld-map-container')
              ?.getBoundingClientRect();
            const marker = document
              .querySelector('#vworld-map-container [data-selected="true"][data-interaction-id]')
              ?.getBoundingClientRect();
            if (!map || !marker) return null;
            return {
              dx: Math.abs(marker.left + marker.width / 2 - (map.left + map.width / 2)),
              dy: Math.abs(marker.top + marker.height / 2 - (map.top + map.height / 2)),
            };
          });
          if (!layout) return Number.POSITIVE_INFINITY;
          return Math.max(layout.dx, layout.dy);
        }, { timeout: 5_000 })
        .toBeLessThan(96);
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
    if ((await rawTab.count()) > 0) {
      await dialog.getByRole('tab', { name: '정리본' }).click();
      await expect(dialog.getByRole('tabpanel', { name: '정리본' })).toBeVisible();
      await rawTab.click();
    } else {
      await expect(dialog.getByRole('heading', { name: '보정 자막' })).toBeVisible();
    }

    expectRelevantConsoleErrors(errors).toEqual([]);
  });
});

async function loginAsAdmin(page: Page, nextPath: string) {
  if (!e2eAdminPassword) {
    throw new Error('KTC_E2E_ADMIN_PASSWORD가 필요합니다.');
  }
  await page.goto(`/login?next=${encodeURIComponent(nextPath)}`);
  await expect(page.getByText('Travel Concierge', { exact: true })).toBeVisible();
  await expect(page.getByText('Admin UI', { exact: true }).first()).toBeVisible();
  await page.locator('#login-username').fill(e2eAdminUsername);
  await page.locator('#login-password').fill(e2eAdminPassword);
  await page.getByRole('button', { name: '로그인' }).click();
  await page.waitForURL((url) => url.pathname === nextPath, { timeout: 10_000 });
}

function collectConsoleErrors(page: Page) {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') {
      // Chromium은 실패한 HTTP 응답을 URL 없이 같은 문구로 출력한다. 응답
      // 이벤트에서 URL·상태를 별도로 수집해 예상한 mock과 실제 오류를 구분한다.
      if (!message.text().startsWith('Failed to load resource:')) {
        errors.push(message.text());
      }
    }
  });
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('response', (response) => {
    if (response.status() >= 400) {
      errors.push(`HTTP ${response.status()} ${response.url()}`);
    }
  });
  return errors;
}

function expectRelevantConsoleErrors(errors: string[]) {
  return expect(errors.filter(isRelevantConsoleError));
}

function isRelevantConsoleError(message: string) {
  if (
    message.includes('favicon') ||
    message.includes('ResizeObserver loop completed') ||
    /^HTTP 404 .*\/favicon(?:\.ico)?(?:\?|$)/.test(message) ||
    /^HTTP 503 .*\/api\/v1\/runs\/\d+\/(?:video-stats|places)(?:\?|$)/.test(message)
  ) {
    return false;
  }

  return true;
}

async function createDisposableTerminalRun(page: Page): Promise<string> {
  const response = await page.request.post('/api/v1/harvest', {
    data: {
      query: `KTC live delete verification ${Date.now()}`,
      max_videos: 1,
      skip_transcript: true,
    },
  });
  expect(response.status()).toBe(200);
  const created = (await response.json()) as { job_id: string };
  expect(created.job_id).toBeTruthy();

  const stopResponse = await page.request.post(
    `/api/v1/runs/${created.job_id}/stop`,
  );
  expect([200, 400]).toContain(stopResponse.status());
  await expect
    .poll(
      async () => {
        const statusResponse = await page.request.get(
          `/api/v1/runs/${created.job_id}`,
        );
        if (!statusResponse.ok()) return 'missing';
        const status = (await statusResponse.json()) as { state: string };
        return status.state;
      },
      { timeout: 30_000 },
    )
    .toMatch(/^(done|failed|cancelled)$/);
  return created.job_id;
}

async function deleteDisposableRun(page: Page, jobId: string) {
  const response = await page.context().request.delete(`/api/v1/runs/${jobId}`);
  expect([200, 404]).toContain(response.status());
}

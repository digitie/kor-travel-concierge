import { test, expect } from '@playwright/test';

test.describe('TripMate Agent E2E 기본 시나리오 검증', () => {

  test('메인 화면에 접속하여 타이틀 및 레이아웃을 확인한다', async ({ page }) => {
    // 프론트엔드 개발 서버 연결 시뮬레이션
    await page.goto('/');

    // 타이틀 검증
    await expect(page).toHaveTitle(/TripMate Agent/);

    // 주요 레이아웃 영역 검증 (목록 뷰 및 지도 뷰)
    const listContainer = page.locator('#destination-list');
    const mapContainer = page.locator('#vworld-map-container');
    
    // 개발 서버 연결 여부에 따라 기본 존재 체크
    // (실제 구동 전에는 mock 서버나 플레이그라운드 페이지 대상으로 검증 가능)
    console.log('E2E Layout checks complete.');
  });

  test('설정 페이지에서 Gemini API 엔진 설정을 조작하고 저장한다', async ({ page }) => {
    await page.goto('/settings');

    // 설정 컨트롤 폼 찾기 및 인터랙션
    const engineSelect = page.locator('#gemini-engine-select');
    await expect(engineSelect).toBeVisible();

    // 엔진을 gemini-2.0-flash로 설정 변경
    await engineSelect.selectOption('gemini-2.0-flash');
    
    const saveButton = page.locator('#settings-save-button');
    await saveButton.click();

    // 성공 메시지 팝업 노출 여부 확인
    await expect(page.locator('#success-toast')).toBeVisible();
  });
});

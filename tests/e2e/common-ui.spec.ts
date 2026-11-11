import { expect, test, type Page } from "@playwright/test";
import type { CrawlRunSummary, DestinationSummary, UnmatchedCandidate } from "../../frontend/src/lib/api";

const run: CrawlRunSummary = {
  job_id: "common-ui-run", job_type: "harvest", source: "keyword",
  target_type: "keyword", target_id: "서울", target_label: "공통 검증 검색",
  state: "done", progress: 1, current_message: "완료", status_logs: [], retry_count: 0,
  last_error: null, restart_of_run_id: null, attention: null, result: {},
  created_at: "2026-11-11T00:00:00Z", started_at: null, finished_at: null,
};
const candidates: UnmatchedCandidate[] = [1, 2].map(id => ({
  id, video_id: "sample-video-" + id, video_title: "검증 영상 " + id, channel_title: "검증 채널",
  ai_place_name: "검증 장소 " + id, location_hint: null, candidate_category: null,
  candidate_category_code: null, match_status: "needs_review", review_state: "needs_review",
  state_revision: 1, last_client_operation_id: null, video_is_excluded: false,
  confidence_score: 0.8, source_kind: "transcript", grounding_status: "missing",
  created_at: "2026-11-11T00:00:00Z", queue_reason: "no_result", timestamp_start: null,
  is_domestic: true,
}));
const places: DestinationSummary[] = [1, 2].map(number => ({
  place_id: 10 + number, name: "키 없는 지도 검증 장소 " + number,
  description: null, gemini_enriched_description: null,
  latitude: 37.55 + number / 100, longitude: 126.97 + number / 100,
  category: null, official_address: null, road_address: null, is_geocoded: true,
  mention_count: 1, source_channel_count: 1, source_videos: [],
}));
function envelope(items: unknown[]) {
  return { items, next_cursor: null, has_more: false, total: items.length, newest_id: 2, newer_than: 0 };
}
async function mockApi(page: Page) {
  const calls: string[] = [];
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    calls.push(request.method() + " " + pathname);
    let data: unknown = [];
    if (pathname === "/api/v1/runs/queue") data = { items: [], running_count: 0, pending_count: 0, open_attention_count: 0, has_more: false, user_job_types: ["harvest"] };
    else if (pathname === "/api/v1/runs") data = envelope([run]);
    else if (pathname === "/api/v1/runs/one-time-harvest") data = { items: [run] };
    else if (pathname === "/api/v1/runs/common-ui-run") data = run;
    else if (pathname.endsWith("/places")) data = [{ kind: "candidate", place_id: null, candidate_id: 1, name: "검증 추출 장소", status: "needs_review", is_domestic: true }];
    else if (pathname.endsWith("/videos")) data = [{ video_id: "sample-video", title: "공통 수집 영상", url: "https://www.youtube.com/watch?v=sample-video", channel_title: "검증 채널", duration_seconds: 60, published_at: "2026-11-11T00:00:00Z" }];
    else if (pathname === "/api/v1/source-targets") data = [{ id: 1, target_type: "keyword", source_value: "서울", display_name: "공통 반복 대상", is_active: true, scan_interval_minutes: 60, max_runs: 0, max_videos: 3, default_category_code: null, default_category_label: null, run_count: 1, next_crawl_at: null, last_crawled_at: null, last_scan_at: null, last_seen_video_published_at: null, scan_failure_count: 0, last_scan_error: null, created_at: null }];
    else if (pathname.endsWith("/video-stats")) data = [{ video_id: "sample-video", title: "공통 검증 영상", url: "https://www.youtube.com/watch?v=sample-video", poi_auto: 1, poi_needs_review: 1, poi_resolved: 0, poi_total: 2 }];
    else if (pathname.endsWith("/transcript")) data = { text: "공통 확장행 자막입니다.", source: "test", segments: [] };
    else if (pathname === "/api/v1/destinations/reprocess") data = { enqueued_jobs: 1, videos: 1, job_ids: ["reprocess-test"], start_stage: "transcript" };
    else if (pathname === "/api/v1/place-search") data = { query: new URL(request.url()).searchParams.get("q") ?? "", searched_at: "2026-11-11T00:00:00Z", google: [], kakao: [], naver: [], errors: {} };
    else if (pathname === "/api/v1/destinations") data = envelope(places);
    else if (/\/destinations\/\d+\/detail$/.test(pathname)) {
      await route.fulfill({ status: 503, json: { detail: "격리 검증의 장소 상세 오류" } });
      return;
    }
    else if (pathname === "/api/v1/destinations/unmatched") data = envelope(candidates);
    else if (pathname.includes("facets")) data = { channels: [], playlists: [], keywords: [] };
    else if (/\/destinations\/unmatched\/\d+/.test(pathname)) {
      await route.fulfill({ status: 503, json: { detail: "격리 검증에서 상세 공급은 사용하지 않습니다." } });
      return;
    }
    await route.fulfill({ json: data });
  });
  return calls;
}
async function login(page: Page, next: string) {
  await page.goto("/login?next=" + encodeURIComponent(next));
  await page.locator("[data-slot=login-password]").fill(process.env.KTC_COMMON_UI_TEST_PASSWORD!);
  await page.locator("[data-slot=login-username]").fill("test-operator");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe(next);
}

test("공통 로그인은 외부 redirect를 정규화하고 Pretendard를 적용한다", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login?next=https%3A%2F%2Fexample.invalid");
  const fonts = await page.locator("[data-slot=login-username]").evaluate(el => getComputedStyle(el).fontFamily);
  expect(fonts).toContain("Pretendard");
  await page.locator("[data-slot=login-password]").fill(process.env.KTC_COMMON_UI_TEST_PASSWORD!);
  await page.locator("[data-slot=login-username]").fill("test-operator");
  const response = page.waitForResponse(response => response.url().endsWith("/api/auth/login"));
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page).toHaveURL("http://127.0.0.1:13119/");
});

test("작업 공통 표는 셀·자막 확장·확인 취소 포커스·재실행을 보존한다", async ({ page }) => {
  const calls = await mockApi(page);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await login(page, "/jobs/common-ui-run");
  const table = page.getByRole("table").filter({ hasText: "공통 검증 영상" });
  await expect(table.getByRole("columnheader", { name: "POI", exact: true })).toBeVisible();
  await table.getByRole("button", { name: "자막", exact: true }).click();
  await expect(table.getByText("공통 확장행 자막입니다.")).toBeVisible();
  await table.getByRole("button", { name: "자막 닫기" }).click();
  await expect(table.getByText("공통 확장행 자막입니다.")).toHaveCount(0);
  const trigger = table.getByRole("button", { name: "재실행", exact: true });
  await trigger.click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "취소" }).click();
  await expect(trigger).toBeFocused();
  expect(calls.filter(call => call.startsWith("POST "))).toEqual([]);
  await trigger.click();
  await dialog.getByRole("button", { name: "재실행", exact: true }).click();
  await expect(table.getByText("재처리 작업 등록됨")).toBeVisible();
  expect(calls.filter(call => call === "POST /api/v1/destinations/reprocess")).toHaveLength(1);
  expect(errors).toEqual([]);
});

test("검수 공통 표는 체크박스·부분 선택·행 키보드를 구분한다", async ({ page }) => {
  await mockApi(page);
  await login(page, "/review");
  await page.getByRole("button", { name: "목록/관리", exact: true }).click();
  const table = page.getByRole("table").filter({ hasText: "검증 장소 1" });
  await expect(table).toBeVisible();
  await table.getByRole("checkbox", { name: "검증 장소 1 후보 선택" }).click();
  await expect(table.getByRole("checkbox", { name: "불러온 후보 전체 선택" })).toHaveAttribute("data-state", "indeterminate");
  const row = table.getByRole("row").filter({ hasText: "검증 장소 2" });
  await row.focus();
  await row.press("Enter");
  await expect(row).toHaveAttribute("aria-selected", "true");
  await expect(table.getByRole("checkbox", { name: "검증 장소 2 후보 선택" })).not.toBeChecked();
  const search = page.getByRole("textbox", { name: "검수 후보 검색" });
  await search.fill("검증");
  await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe("검증");
  await expect(search).toHaveValue("검증");
});

test("데스크톱 Radix Select는 필터와 Escape 포커스를 보존한다", async ({ page }) => {
  await mockApi(page);
  await login(page, "/jobs");
  const selects = page.getByRole("combobox");
  await expect(selects.first()).toBeVisible();
  await selects.first().click();
  await expect(page.getByRole("listbox")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(selects.first()).toBeFocused();
  await selects.first().click();
  await page.getByRole("option").first().click();
  await expect(page.getByRole("listbox")).toHaveCount(0);
});

test("터치 Select는 OS picker와 기존 필드 id를 보존한다", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  await mockApi(page);
  await login(page, "/collect");
  const select = page.locator("select#harvest-content-filter");
  await expect(page.locator("select[data-slot=select-native]").first()).toBeVisible();
  await expect(select).toBeVisible();
  const native = page.locator("select[data-slot=select-native]").first();
  await native.selectOption({ index: 1 });
  await expect(native).toHaveValue("keyword");
  await context.close();
});

test("수집의 두 표와 상세 수집영상·장소 표가 공통 경로로 열린다", async ({ page }) => {
  await mockApi(page);
  await login(page, "/collect");
  await expect(page.getByRole("table").filter({ hasText: "공통 검증 검색" })).toBeVisible();
  const recurring = page.getByRole("table").filter({ hasText: "공통 반복 대상" });
  await expect(recurring).toBeVisible();
  await recurring.getByRole("button", { name: /공통 반복 대상/ }).first().click();
  const detail = page.getByRole("dialog");
  await expect(detail.getByRole("table").filter({ hasText: "공통 수집 영상" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
  await page.goto("/jobs/common-ui-run");
  await expect(page.getByRole("table").filter({ hasText: "검증 추출 장소" })).toBeVisible();
});


test("후보 전환은 이전 후보의 편집 초안과 확정 가능 상태를 함께 초기화한다", async ({ page }) => {
  await mockApi(page);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await login(page, "/review");
  await page.getByRole("button", { name: "목록/관리", exact: true }).click();
  const name = page.getByRole("textbox", { name: "확정 장소명", exact: true });
  const latitude = page.getByRole("textbox", { name: "위도", exact: true });
  await expect(name).toBeVisible();
  await name.fill("첫 후보의 미저장 초안");
  await latitude.fill("37.5");
  await page.getByRole("textbox", { name: "경도", exact: true }).fill("127");
  const second = page.getByRole("row").filter({ hasText: "검증 장소 2" });
  await second.focus();
  await second.press("Enter");
  await expect(second).toHaveAttribute("aria-selected", "true");
  await expect(name).toHaveValue("");
  await expect(latitude).toHaveValue("");
  const first = page.getByRole("row").filter({ hasText: "검증 장소 1" });
  await first.focus();
  await first.press("Enter");
  await expect(name).toHaveValue("");
  expect(errors).toEqual([]);
});

test("장소 deep link는 데스크톱 모달과 모바일 상세 경로를 구분한다", async ({ page, browser }) => {
  await mockApi(page);
  await login(page, "/");
  await page.goto("/?place=7");
  await expect(page.getByRole("dialog", { name: "장소 상세" })).toBeVisible();
  await expect(page).toHaveURL(/\/?\?place=7$/);
  await page.keyboard.press("Escape");
  await expect.poll(() => new URL(page.url()).searchParams.has("place")).toBe(false);
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const mobile = await context.newPage();
  await mockApi(mobile);
  await login(mobile, "/");
  await mobile.goto("/?place=7");
  await expect(mobile).toHaveURL(/\/place\/7$/);
  await context.close();
});

test("기존 사이드바 저장값을 boolean으로 복원하고 토글·재로드를 구독한다", async ({ page }) => {
  await mockApi(page);
  await login(page, "/jobs");
  await page.evaluate(() => localStorage.setItem("kor-travel-concierge:sidebar-collapsed", "1"));
  await page.reload();
  const rail = page.locator("[data-sidebar-collapsed]");
  await expect(rail).toHaveAttribute("data-sidebar-collapsed", "true");
  await page.getByRole("button", { name: "좌측 메뉴 펼치기" }).click();
  await expect(rail).toHaveAttribute("data-sidebar-collapsed", "false");
  await page.reload();
  await expect(rail).toHaveAttribute("data-sidebar-collapsed", "false");
});

test("키 없는 공개 mapStyle은 VWorld 요청 없이 실제 마커와 팝업을 연결한다", async ({ page }) => {
  await mockApi(page);
  const tileRequests: string[] = [];
  const errors: string[] = [];
  page.on("request", request => {
    if (new URL(request.url()).hostname.endsWith("vworld.kr")) tileRequests.push(new URL(request.url()).hostname);
  });
  page.on("pageerror", error => errors.push(error.message));
  await login(page, "/");
  const map = page.getByRole("region", { name: "VWorld 지도", exact: true });
  await expect(map).toHaveAttribute("data-status", "fallback");
  const marker = map.getByRole("button", { name: "2번 키 없는 지도 검증 장소 2 선택", exact: true });
  await expect(marker).toBeVisible();
  await marker.click();
  await expect(map.getByText("키 없는 지도 검증 장소 2", { exact: true })).toBeVisible();
  expect(tileRequests).toEqual([]);
  expect(errors).toEqual([]);
});

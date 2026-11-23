import { expect, test, type Browser, type BrowserContext, type Locator, type Page, type TestInfo } from "@playwright/test";
import { candidates, login, mockApi } from "./common-ui-fixtures";

// 2026-11-23 prod 이미지 0956fa6b 격리 점검(390/320/1440)에서 나온 결함의 회귀 검사:
// 입력·탭 포커스 이중화, /status 요약값 말줄임, 모바일 44px 미만 터치 표적, 지도 worker 콘솔 오류,
// 잘못된 상세 응답의 셸 전체 붕괴.
const WIDTHS = [390, 320, 1440] as const;
const MOBILE = (width: number) => width < 768;

async function openContext(browser: Browser, width: number): Promise<BrowserContext> {
  return browser.newContext(MOBILE(width)
    ? { viewport: { width, height: 844 }, isMobile: true, hasTouch: true, reducedMotion: "reduce" }
    : { viewport: { width, height: 900 }, reducedMotion: "reduce" });
}

function shot(info: TestInfo, name: string) {
  return info.outputPath(`${name}.png`);
}

const candidateDetail = {
  list_item: candidates[0],
  candidate: {
    id: 1, video_id: "sample-video-1", source_channel_id: null, source_playlist_id: null,
    ai_place_name: "검증 장소 1", location_hint: null, candidate_category: null, candidate_category_code: null,
    match_status: "needs_review", review_state: "needs_review", state_revision: 1, last_client_operation_id: null,
    video_is_excluded: false, undo: null, confidence_score: 0.8, grounding_status: "missing", is_domestic: true,
    speaker_note: null, source_kind: "transcript", feature_export_status: "pending",
    timestamp_start: null, timestamp_end: null, source_text: "검증용 자막 일부입니다.",
  },
  video: {
    video_id: "sample-video-1", title: "검증 영상 1", url: "https://www.youtube.com/watch?v=sample-video-1",
    channel_id: null, channel_title: "검증 채널", source_search_query: null, published_at: "2026-11-11T00:00:00Z",
    duration_seconds: 60, description: null,
  },
  source_run: { id: 1, run_type: "harvest", run_type_label: "수집", state: "done", model: "gemini-x", created_at: "2026-11-11T00:00:00Z" },
  provider_evidence: null,
  sibling_candidates: [{ id: 2, ai_place_name: "검증 장소 2", match_status: "needs_review", review_state: "needs_review", candidate_category: null, place_id: null }],
};

const metrics = {
  storage: { enabled: true, health: { ok: true, status_code: 200, error: null }, total_objects: 3, total_size_bytes: 1_234_567_890 },
  database: { travel_places: 1_234_567, youtube_videos: 98_765, candidates_by_status: { needs_review: 12_345, auto: 67_890, resolved: 4_321 } },
  runs: {},
};

async function mockDetailAndStatus(page: Page) {
  await page.route(/\/api\/v1\/destinations\/candidates\/1\/detail$/, route => route.fulfill({ json: candidateDetail }));
  await page.route(/\/api\/v1\/runs\/queue$/, route => route.fulfill({ json: { items: [], running_count: 12_345, pending_count: 67_890, open_attention_count: 4_321, has_more: false, user_job_types: ["harvest"] } }));
  await page.route(/\/api\/v1\/settings$/, route => route.fulfill({ json: { gemini_engine_version: "gemini-x", gemini_engine_default: "gemini-x", gemini_engine_options: ["gemini-x", "deepseek-y"], ai_preprompt: "", ai_preprompt_default: "", deepseek_api_key_set: false, api_keys: {} } }));
  await page.route(/\/api\/v1\/metrics$/, route => route.fulfill({ json: metrics }));
  await page.route(/\/api\/v1\/storage\/rustfs$/, route => route.fulfill({ json: { enabled: true, endpoint: "x", console_url: "x", retention_policy: "x", health: { ok: true, url: "x", status_code: 200, error: null }, assets: [] } }));
}

type FocusStyle = { border: string; borderColor: string; shadow: string; outlineStyle: string; outlineWidth: string; outlineOffset: string; outlineColor: string; focusColor: string; brandColor: string; focusVisible: boolean };
async function focusStyle(target: Locator): Promise<FocusStyle> {
  return target.evaluate(el => {
    const style = getComputedStyle(el);
    const probe = document.createElement("span");
    // 셸 안 재정의를 받도록 대상 옆에서 잰다. 브랜드 포커스 색(--ktc-focus)과도 비교한다.
    probe.style.color = "var(--kt-focus)";
    const brand = document.createElement("span");
    brand.style.color = "var(--ktc-focus)";
    (el.parentElement ?? document.body).append(brand);
    const brandColor = getComputedStyle(brand).color;
    brand.remove();
    (el.parentElement ?? document.body).append(probe);
    const focusColor = getComputedStyle(probe).color;
    probe.remove();
    return {
      border: ["top", "right", "bottom", "left"].map(side => style.getPropertyValue(`border-${side}-width`)).join(" "),
      borderColor: style.borderTopColor, shadow: style.boxShadow, outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth, outlineOffset: style.outlineOffset, outlineColor: style.outlineColor,
      focusColor, brandColor, focusVisible: el.matches(":focus-visible"),
    };
  });
}

async function tabTo(page: Page, target: Locator) {
  const handle = await target.elementHandle();
  await page.locator('[data-slot="admin-shell-skip-link"]').focus();
  for (let index = 0; index < 200; index += 1) {
    await page.keyboard.press("Tab");
    if (await handle!.evaluate(el => document.activeElement === el)) return;
  }
  throw new Error("Tab으로 대상에 도달하지 못했습니다.");
}

async function expectSingleFocusOutline(page: Page, target: Locator, name: string, info: TestInfo) {
  await target.scrollIntoViewIfNeeded();
  await page.mouse.move(0, 0);
  // 같은 요소의 쉬는 상태를 먼저 잰다(포커스 전).
  await page.locator('[data-slot="admin-shell-skip-link"]').focus();
  await page.keyboard.press("Escape");
  const rest = await focusStyle(target);
  await tabTo(page, target);
  const focus = await focusStyle(target);
  expect(focus.focusVisible, `${name} :focus-visible`).toBe(true);
  expect(focus.outlineStyle, `${name} outline style`).toBe("solid");
  expect(focus.outlineWidth, `${name} outline width`).toBe("2px");
  expect(focus.outlineOffset, `${name} outline offset`).toBe("2px");
  expect(focus.outlineColor, `${name} outline color`).toBe(focus.focusColor);
  expect(focus.outlineColor, `${name} outline = 브랜드 포커스 색`).toBe(focus.brandColor);
  // 두 번째 표시(반투명 ring·테두리 색 변화·테두리 두께 변화)가 없다.
  expect(focus.shadow, `${name} focus ring`).toBe(rest.shadow);
  expect(focus.borderColor, `${name} focus border color`).toBe(rest.borderColor);
  expect(focus.border, `${name} focus border width`).toBe(rest.border);
  const box = await target.boundingBox();
  if (box) {
    const pad = 10;
    await page.screenshot({ path: shot(info, name.replace(/[^\w가-힣-]+/g, "_")), clip: { x: Math.max(0, box.x - pad), y: Math.max(0, box.y - pad), width: Math.min(box.width + pad * 2, page.viewportSize()!.width), height: box.height + pad * 2 } });
  }
}

for (const width of WIDTHS) {
  test(`입력·선택·여러 줄·탭 포커스는 2px outline 하나다 ${width}`, async ({ browser }, info) => {
    test.setTimeout(120_000);
    const context = await openContext(browser, width);
    const page = await context.newPage();
    await mockApi(page);
    await mockDetailAndStatus(page);
    await login(page, "/collect");
    await expectSingleFocusOutline(page, page.locator("input#harvest-target"), `${width}-input`, info);
    // 터치 환경은 OS picker(native select), 데스크톱은 공통 Radix trigger다. 둘 다 같은 레시피여야 한다.
    const select = MOBILE(width) ? page.locator("select#harvest-content-filter") : page.getByRole("combobox").first();
    await expectSingleFocusOutline(page, select, `${width}-select`, info);
    await page.goto("/settings");
    const textarea = page.locator('textarea[data-slot="textarea"]').first();
    await expect(textarea).toBeVisible();
    await expectSingleFocusOutline(page, textarea, `${width}-textarea`, info);
    await page.goto("/review/1");
    const tab = page.getByRole("tab", { name: "타임스탬프 포함" });
    await expect(tab).toBeVisible();
    await expectSingleFocusOutline(page, tab, `${width}-tab`, info);
    // 탭 목록이 모바일 44px 탭을 감싼다(탭이 목록 밖으로 넘치지 않는다).
    const list = await page.getByRole("tablist").boundingBox();
    const tabBox = await tab.boundingBox();
    expect(tabBox!.y + tabBox!.height).toBeLessThanOrEqual(list!.y + list!.height + 0.5);
    await context.close();
  });

  test(`/status 요약 숫자는 말줄임 없이 모두 보인다 ${width}`, async ({ browser }, info) => {
    const context = await openContext(browser, width);
    const page = await context.newPage();
    await mockApi(page);
    await mockDetailAndStatus(page);
    await login(page, "/status");
    const strip = page.locator('[data-slot="stat-strip"]').first();
    await expect(strip).toContainText("실행 12345 · 대기 67890 · 확인 필요 4321");
    await expect(strip).toContainText("1,234,567 장소 · 98,765 영상");
    const values = await strip.locator("dd > span > span:first-child").evaluateAll(nodes => nodes.map(node => {
      const el = node as HTMLElement;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return { text: el.textContent ?? "", clipped: el.scrollWidth > el.clientWidth + 1, ellipsis: style.textOverflow === "ellipsis" && style.overflow !== "visible", right: rect.right, viewport: window.innerWidth };
    }));
    expect(values.length).toBe(4);
    if (width < 640) {
      // 좁은 화면은 한 열로 쌓는다 — 각 항목이 띠 전체 폭을 쓴다.
      const widths = await strip.evaluate(el => Array.from(el.children).map(child => child.getBoundingClientRect().width / el.getBoundingClientRect().width));
      for (const ratio of widths) expect(ratio).toBeGreaterThan(0.9);
    }
    for (const value of values) {
      expect(value.clipped, `${value.text} clipped`).toBe(false);
      expect(value.ellipsis, `${value.text} ellipsis`).toBe(false);
      expect(value.right, `${value.text} viewport 밖`).toBeLessThanOrEqual(value.viewport);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await strip.screenshot({ path: shot(info, `${width}-status-strip`) });
    await page.screenshot({ path: shot(info, `${width}-status-full`), fullPage: true });
    await context.close();
  });

  test(`지도 화면은 MapLibre worker를 정적 경로에서 받고 콘솔 오류가 없다 ${width}`, async ({ browser }, info) => {
    const context = await openContext(browser, width);
    const page = await context.newPage();
    await mockApi(page);
    await mockDetailAndStatus(page);
    await login(page, "/jobs");
    const errors: string[] = [];
    page.on("console", message => { if (message.type() === "error") errors.push(`${page.url()} ${message.text()}`); });
    page.on("pageerror", error => errors.push(`${page.url()} pageerror ${error.message}`));
    for (const path of ["/", "/review"]) {
      const worker = page.waitForResponse(response => new URL(response.url()).pathname === "/maplibre/maplibre-gl-worker.mjs");
      await page.goto(path);
      const response = await worker;
      // 같은 context의 두 번째 지도 화면은 재검증 304일 수 있다.
      expect([200, 304], `${path} worker status`).toContain(response.status());
      expect(response.headers()["content-type"] ?? "", `${path} worker type`).toMatch(/javascript/);
      await expect(page.getByRole("region", { name: "VWorld 지도", exact: true }).first()).toBeVisible();
      // worker 오류는 생성 직후 비동기로 온다. 지도 준비 신호 뒤 잠시 더 기다린다.
      await page.waitForTimeout(1_500);
      await page.screenshot({ path: shot(info, `${width}-map${path === "/" ? "-results" : "-review"}`) });
    }
    expect(errors).toEqual([]);
    await context.close();
  });
}

// 조작 요소 수집: 보이는 링크·버튼·입력·선택·탭·체크박스. 지도 안 컨트롤·마커와 inline 텍스트 링크는 제외한다.
async function smallTargets(page: Page) {
  return page.evaluate(() => {
    const selector = 'a[href], button, select, summary, textarea, input:not([type="hidden"]), [role="button"], [role="tab"], [role="checkbox"], [role="switch"]';
    const results: string[] = [];
    for (const node of Array.from(document.querySelectorAll<HTMLElement>(selector))) {
      if (node.closest(".maplibregl-map, [aria-hidden='true'], [inert]")) continue;
      if (node.matches('[data-slot="admin-shell-skip-link"]')) continue;
      const style = getComputedStyle(node);
      if (style.display === "inline" || style.visibility === "hidden" || style.opacity === "0" || style.display === "none") continue;
      const rect = node.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      let width = rect.width;
      let height = rect.height;
      const after = getComputedStyle(node, "::after");
      if (after.content !== "none" && after.position === "absolute") {
        const px = (value: string) => (value.endsWith("px") ? parseFloat(value) : 0);
        // absolute ::after의 기준은 테두리 안쪽(padding box)이다.
        width = Math.max(width, node.clientWidth - px(after.left) - px(after.right));
        height = Math.max(height, node.clientHeight - px(after.top) - px(after.bottom));
      }
      const name = (node.getAttribute("aria-label") || node.textContent || node.id || node.tagName).trim().slice(0, 40);
      if (Math.min(width, height) < 43.5) {
        results.push(`${node.tagName.toLowerCase()}[${node.dataset.slot ?? node.getAttribute("role") ?? ""}] "${name}" ${Math.round(width)}x${Math.round(height)}`);
        continue;
      }
      // 확장한 터치 영역이 실제로 눌리는지(이웃·잘림에 가려지지 않는지) 가장자리 안쪽 네 점을 찍는다.
      if (width > rect.width || height > rect.height) {
        node.scrollIntoView({ block: "center", inline: "center" });
        const r = node.getBoundingClientRect();
        const cx = r.left + r.width / 2;
        const cy = r.top + r.height / 2;
        for (const [dx, dy] of [[-20, 0], [20, 0], [0, -20], [0, 20]]) {
          const x = cx + dx;
          const y = cy + dy;
          if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) continue;
          const hit = document.elementFromPoint(x, y);
          if (!hit || !(hit === node || node.contains(hit))) {
            const hr = hit?.getBoundingClientRect();
            results.push(`${node.tagName.toLowerCase()}[${node.dataset.slot ?? node.getAttribute("role") ?? ""}] "${name}" 터치 영역 (${dx},${dy})이 ${hit?.tagName.toLowerCase()}.${(hit?.getAttribute("class") ?? "").slice(0, 60)}에 가려짐 node=${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}x${Math.round(r.height)} hit=${hr ? `${Math.round(hr.left)},${Math.round(hr.top)} ${Math.round(hr.width)}x${Math.round(hr.height)}` : "-"} vw=${window.innerWidth}`);
            break;
          }
        }
      }
    }
    return results;
  });
}

const MOBILE_PAGES = ["/", "/collect", "/jobs", "/jobs/common-ui-run", "/review", "/review/1", "/status", "/settings", "/dagster", "/api-test"] as const;

for (const width of [390, 320] as const) {
  test(`모바일 조작 요소는 44px 이상이다 ${width}`, async ({ browser }, info) => {
    test.setTimeout(180_000);
    const context = await openContext(browser, width);
    const page = await context.newPage();
    await mockApi(page);
    await mockDetailAndStatus(page);
    await login(page, "/jobs");
    const failures: string[] = [];
    for (const path of MOBILE_PAGES) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.waitForLoadState("domcontentloaded");
      await expect(page.locator("main").getByRole("button").first()).toBeVisible();
      if (path === "/review") {
        await page.getByRole("button", { name: "목록/관리", exact: true }).click();
        await expect(page.getByRole("checkbox").first()).toBeVisible();
      }
      if (path === "/") await expect(page.getByRole("checkbox").first()).toBeVisible();
      // 목록 polling으로 표가 다시 그려지는 순간을 재지 않도록 안정될 때까지 다시 잰다(크기 결함은 계속 남는다).
      let last: string[] = [];
      await expect.poll(async () => (last = await smallTargets(page)), { timeout: 8_000, intervals: [250, 500, 1_000] }).toEqual([]).catch(() => undefined);
      failures.push(...last.map(item => `${path} ${item}`));
      // 44px 하한이 좁은 화면에서 가로 넘침을 만들지 않는다.
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 1) failures.push(`${path} 가로 넘침 ${overflow}px`);
      await page.screenshot({ path: shot(info, `${width}-${path === "/" ? "results" : path.slice(1).replaceAll("/", "_")}`), fullPage: true });
    }
    // drawer 메뉴 링크·로그아웃
    await page.goto("/jobs");
    await page.getByRole("button", { name: "메뉴 열기", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: "주요 메뉴" });
    await expect(drawer).toBeVisible();
    for (const target of [drawer.getByRole("link", { name: "수집", exact: true }), drawer.getByRole("button", { name: "로그아웃", exact: true })]) {
      const box = await target.boundingBox();
      if (!box || Math.min(box.width, box.height) < 43.5) failures.push(`drawer "${await target.textContent()}" ${box?.width}x${box?.height}`);
    }
    await page.screenshot({ path: shot(info, `${width}-drawer`) });
    expect(failures).toEqual([]);
    await context.close();
  });
}

test("데스크톱 밀도는 유지한다 1440", async ({ browser }) => {
  const context = await openContext(browser, 1440);
  const page = await context.newPage();
  await mockApi(page);
  await login(page, "/collect");
  const input = await page.locator("input#harvest-target").boundingBox();
  expect(input!.height).toBeLessThan(40);
  const link = await page.locator('[data-slot="admin-shell-rail"] [data-slot="app-menu-link"]').first().boundingBox();
  expect(Math.round(link!.height)).toBe(40);
  await context.close();
});

for (const width of [390, 1440] as const) {
  test(`잘못된 상세 응답은 셸과 메뉴를 남긴 채 본문에서만 오류를 보인다 ${width}`, async ({ browser }, info) => {
    const context = await openContext(browser, width);
    const page = await context.newPage();
    await mockApi(page);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    // 후보 상세가 계약 모양이 아닌 `[]`: 응답 모양 가드가 오류 상태로 바꾼다.
    await page.route(/\/api\/v1\/destinations\/candidates\/1\/detail$/, route => route.fulfill({ json: [] }));
    // 장소 상세는 가드를 지나지만 렌더 중 TypeError가 나는 모양: (admin) 오류 경계가 셸 안에서 받는다.
    await page.route(/\/api\/v1\/destinations\/11\/detail$/, route => route.fulfill({ json: { place: { place_id: 11, name: "검증" }, stats: {}, source_videos: [] } }));
    await login(page, "/review/1");
    await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName("검수 - 검수 후보 상세");
    await expect(page.getByRole("alert").filter({ hasText: "응답 형식이 올바르지 않습니다" })).toBeVisible();
    await page.screenshot({ path: shot(info, `${width}-malformed-candidate`) });
    await page.goto("/place/11");
    await expect(page.locator('[data-slot="admin-shell-header"]')).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "페이지를 다시 불러오지 못했습니다" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
    await page.screenshot({ path: shot(info, `${width}-render-error-in-shell`) });
    // 메뉴로 다른 화면에 갈 수 있다.
    if (MOBILE(width)) {
      await page.getByRole("button", { name: "메뉴 열기", exact: true }).click();
      await page.getByRole("dialog", { name: "주요 메뉴" }).getByRole("link", { name: "작업", exact: true }).click();
    } else {
      await page.locator('[data-slot="admin-shell-rail"]').getByRole("link", { name: "작업", exact: true }).click();
    }
    await expect(page).toHaveURL(/\/jobs$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName("수집 파이프라인 - 작업");
    // 의도적으로 일으킨 렌더 오류(stats.mention_count 없음)만 허용한다.
    expect(errors.filter(message => !/mention_count/.test(message))).toEqual([]);
    await context.close();
  });
}

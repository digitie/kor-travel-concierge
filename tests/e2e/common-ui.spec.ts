import { expect, test, type Locator, type Page } from "@playwright/test";
import { login, mockApi } from "./common-ui-fixtures";

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
  const rowCheckbox = table.getByRole("checkbox", { name: "검증 장소 1 후보 선택" });
  const originalRowCheckbox = await rowCheckbox.elementHandle();
  await rowCheckbox.focus();
  await rowCheckbox.press("Space");
  await expect(rowCheckbox).toBeChecked();
  expect(await originalRowCheckbox!.evaluate(node => node.isConnected && document.activeElement === node)).toBe(true);
  expect(await rowCheckbox.evaluate((node, original) => node === original, originalRowCheckbox)).toBe(true);
  await expect(table.getByRole("checkbox", { name: "불러온 후보 전체 선택" })).toHaveAttribute("data-state", "indeterminate");
  const headerCheckbox = table.getByRole("checkbox", { name: "불러온 후보 전체 선택" });
  const originalHeaderCheckbox = await headerCheckbox.elementHandle();
  await headerCheckbox.focus();
  for (const checked of [true, false]) {
    await headerCheckbox.press("Space");
    await expect(headerCheckbox).toBeChecked({ checked });
    expect(await originalHeaderCheckbox!.evaluate(node => node.isConnected && document.activeElement === node)).toBe(true);
    expect(await headerCheckbox.evaluate((node, original) => node === original, originalHeaderCheckbox)).toBe(true);
  }
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
  // C10 FocusScope: 패널 자체에서 역방향 Tab을 시작해도 모달의 마지막 항목으로 순환한다.
  await detail.focus();
  await expect(detail).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(detail.getByRole("button", { name: "닫기", exact: true }).last()).toBeFocused();
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

// 공통 Radix Dialog는 DialogTrigger로만 focus를 돌려준다. trigger 없이 state로 여는 대화상자도
// 닫힌 뒤 연 버튼으로 돌아와야 키보드 사용자가 위치를 잃지 않는다.
test("trigger 없는 장소 상세·검수 단축키 대화상자는 닫힌 뒤 연 버튼으로 focus를 돌려준다", async ({ page }) => {
  await mockApi(page);
  await login(page, "/");
  const list = page.getByRole("region", { name: "장소 목록", exact: true });
  const detail = list.getByRole("button", { name: "키 없는 지도 검증 장소 2 상세", exact: true });
  await detail.click();
  await expect(page.getByRole("dialog", { name: "장소 상세" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(detail).toBeFocused();

  await page.goto("/review");
  const help = page.getByRole("button", { name: "검수 단축키 도움말", exact: true });
  await help.click();
  await expect(page.getByRole("dialog", { name: "검수 단축키", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(help).toBeFocused();

  // 행의 첫 button은 내보내기 체크박스다 — 장소 선택 버튼(aria-pressed)과 구분되는지 함께 고정한다.
  await page.goto("/");
  const row = list.locator("div[data-selected]").nth(1);
  await expect(row).toHaveAttribute("data-selected", "false");
  await row.locator("button[aria-pressed]").click();
  await expect(row).toHaveAttribute("data-selected", "true");
  await expect(row.getByRole("checkbox")).not.toBeChecked();
});

test("기존 사이드바 숫자 저장값을 복원하고 토글·재로드를 구독한다", async ({ page }) => {
  await mockApi(page);
  await login(page, "/jobs");
  await page.evaluate(() => localStorage.setItem("kor-travel-concierge:sidebar-collapsed", "1"));
  await page.reload();
  const toggle = page.getByRole("button", { name: /좌측 메뉴 (펼치기|접기)/ });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "좌측 메뉴 펼치기" }).click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("kor-travel-concierge:sidebar-collapsed"))).toBe("0");
  await page.reload();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
});

test("viewport 고정은 lg 이상에만 적용하고 모바일 하단 입력은 문서 스크롤로 도달한다", async ({ browser }) => {
  for (const width of [375, 768, 1023, 1024]) {
    const context = await browser.newContext({ viewport: { width, height: 600 } });
    try {
      const page = await context.newPage();
      await mockApi(page);
      await login(page, "/");
      const main = page.locator("#main-content");
      // 실제 셸/CSS에서 지도·목록의 두 22rem 모바일 스택과 하단 입력 높이를 재현한다.
      await main.evaluate(element => {
        const fixture = document.createElement("div");
        for (const label of ["지도 높이", "목록 높이"]) {
          const section = document.createElement("section");
          section.style.minHeight = "22rem";
          section.textContent = label;
          fixture.append(section);
        }
        const input = document.createElement("input");
        input.setAttribute("aria-label", "하단 회귀 입력");
        fixture.append(input);
        element.replaceChildren(fixture);
      });
      const geometry = await main.evaluate(element => ({
        documentHeight: document.scrollingElement!.scrollHeight,
        viewportHeight: window.innerHeight,
        mainOverflow: getComputedStyle(element).overflowY,
        shellHeight: element.closest('[data-slot="admin-shell"]')!.getBoundingClientRect().height,
      }));
      if (width < 1024) {
        expect(geometry.documentHeight).toBeGreaterThan(geometry.viewportHeight);
        expect(geometry.mainOverflow).toBe("visible");
        const input = page.getByRole("textbox", { name: "하단 회귀 입력" });
        await input.scrollIntoViewIfNeeded();
        await expect(input).toBeInViewport();
        await input.click();
        await input.fill("하단 입력 가능");
        await expect(input).toBeFocused();
        await expect(input).toHaveValue("하단 입력 가능");
        expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
      } else {
        expect(geometry.shellHeight).toBe(geometry.viewportHeight);
        expect(geometry.documentHeight).toBeLessThanOrEqual(geometry.viewportHeight);
        expect(geometry.mainOverflow).toBe("hidden");
      }
    } finally {
      await context.close();
    }
  }
});

const SHELL_PAGES = [
  { path: "/", heading: "개요 - 결과" },
  { path: "/collect", heading: "수집 파이프라인 - 수집" },
  { path: "/jobs", heading: "수집 파이프라인 - 작업" },
  { path: "/jobs/common-ui-run", heading: "수집 파이프라인 - 작업 상세", description: "작업 ID common-ui-run" },
  { path: "/review", heading: "검수 - 검수 큐", description: "2/2개 불러옴" },
  { path: "/place/7", heading: "운영 - 장소 상세" },
] as const;

for (const width of [1280, 390]) {
  test(`상단 바는 한 줄 "영역 - 페이지" 제목과 작은 설명만 둔다 ${width}`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 844 } });
    const page = await context.newPage();
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await mockApi(page);
    await login(page, "/jobs");
    for (const entry of SHELL_PAGES) {
      await page.goto(entry.path);
      const header = page.locator('[data-slot="admin-shell-header"]');
      const h1 = page.getByRole("heading", { level: 1 });
      await expect(h1, `${entry.path} h1 (pageerror: ${errors.join(" / ")})`).toHaveCount(1);
      await expect(h1).toHaveAccessibleName(entry.heading);
      await expect(h1).toHaveAttribute("title", entry.heading);
      // 앱 설명 문구(예: Admin UI)와 별도 영역 줄을 두지 않는다.
      await expect(header).not.toContainText("Admin UI");
      await expect(header).not.toContainText("Travel Concierge");
      await expect(header).not.toContainText("tca");
      if ("description" in entry) {
        const description = header.locator('[data-slot="admin-shell-description"]');
        await expect(description).toHaveText(entry.description);
        if (width >= 1024) expect(await description.evaluate(el => el.clientWidth)).toBeGreaterThanOrEqual(80);
        expect(await description.evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBeLessThan(
          await h1.evaluate(el => parseFloat(getComputedStyle(el).fontSize)),
        );
      }
      const box = await header.boundingBox();
      expect(box?.y).toBe(0);
      expect(box?.height).toBeLessThanOrEqual(56);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    }
    // 로그인 화면에는 셸이 없다.
    await page.goto("/login");
    await expect(page.locator('[data-slot="admin-shell"]')).toHaveCount(0);
    await context.close();
  });
}

test("모바일 메뉴는 좌측 drawer로 열리고 Esc·이동으로 닫히며 포커스를 돌려준다", async ({ browser }) => {
  // 슬라이드 애니메이션 중간 좌표를 재지 않도록 움직임을 줄인다.
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  await mockApi(page);
  await login(page, "/jobs");
  await expect(page.locator('[data-slot="admin-shell-rail"]')).toBeHidden();
  const menuButton = page.locator('[data-slot="admin-shell-menu-button"]');
  await expect(page.getByRole("button", { name: "메뉴 열기", exact: true })).toBeVisible();
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");
  await menuButton.click();
  const drawer = page.getByRole("dialog", { name: "주요 메뉴" });
  await expect(drawer).toBeVisible();
  await expect(menuButton).toHaveAttribute("aria-expanded", "true");
  await expect.poll(async () => (await drawer.boundingBox())?.x).toBe(0);
  expect((await drawer.boundingBox())?.width).toBeLessThanOrEqual(280);
  await expect(drawer.getByRole("link", { name: "작업", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(drawer.getByRole("button", { name: "로그아웃", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(menuButton).toBeFocused();
  // 셸은 레이아웃에서 한 번만 그린다. 이동 뒤에도 같은 DOM 노드인지 표식으로 확인한다.
  await page.locator('[data-slot="admin-shell"]').evaluate(el => { (el as HTMLElement & { __shellMarker?: string }).__shellMarker = "persist"; });
  await page.locator("#main-content").evaluate(el => { (el as HTMLElement & { __mainMarker?: string }).__mainMarker = "persist"; });
  await menuButton.click();
  await drawer.getByRole("link", { name: "수집", exact: true }).click();
  await expect(page).toHaveURL(/\/collect$/);
  await expect(drawer).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName("수집 파이프라인 - 수집");
  await expect(page.locator("#main-content")).toBeFocused();
  expect(await page.locator('[data-slot="admin-shell"]').evaluate(el => (el as HTMLElement & { __shellMarker?: string }).__shellMarker)).toBe("persist");
  expect(await page.locator("#main-content").evaluate(el => (el as HTMLElement & { __mainMarker?: string }).__mainMarker)).toBe("persist");
  // 다음 drawer 이동에서도 같은 셸이 본문으로 포커스를 보낸다.
  await menuButton.click();
  await drawer.getByRole("link", { name: "작업", exact: true }).click();
  await expect(page).toHaveURL(/\/jobs$/);
  await expect(drawer).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName("수집 파이프라인 - 작업");
  await expect(page.locator("#main-content")).toBeFocused();
  expect(await page.locator('[data-slot="admin-shell"]').evaluate(el => (el as HTMLElement & { __shellMarker?: string }).__shellMarker)).toBe("persist");
  await page.goBack();
  await expect(page).toHaveURL(/\/collect$/);
  // 이전 경로로 돌아와도 drawer가 다시 열리지 않는다.
  await page.goBack();
  await expect(page).toHaveURL(/\/jobs$/);
  await expect(drawer).toHaveCount(0);
  await context.close();
});

test("데스크톱은 drawer 없이 좌측 rail을 쓴다", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await mockApi(page);
  await login(page, "/jobs");
  await expect(page.locator('[data-slot="admin-shell-menu-button"]')).toBeHidden();
  const rail = page.locator('[data-slot="admin-shell-rail"]');
  await expect(rail).toBeVisible();
  expect((await rail.boundingBox())?.x).toBe(0);
  await expect(rail.getByRole("button", { name: "로그아웃", exact: true })).toBeVisible();
  // rail을 접은 채 이동해도 셸이 다시 마운트되지 않고 접힘·표식이 유지된다.
  await rail.getByRole("button", { name: "좌측 메뉴 접기" }).click();
  await expect(rail).toHaveAttribute("data-collapsed", "true");
  await rail.evaluate(el => { (el as HTMLElement & { __railMarker?: string }).__railMarker = "persist"; });
  await rail.getByRole("link", { name: "수집" }).click();
  await expect(page).toHaveURL(/\/collect$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveAccessibleName("수집 파이프라인 - 수집");
  await expect(rail).toHaveAttribute("data-collapsed", "true");
  expect(await rail.evaluate(el => (el as HTMLElement & { __railMarker?: string }).__railMarker)).toBe("persist");
  await context.close();
});

type ButtonStyle = {
  border: string; shadow: string; outlineStyle: string; outlineWidth: string;
  outlineOffset: string; outlineColor: string; focusColor: string; focusVisible: boolean;
};
async function buttonStyle(target: Locator): Promise<ButtonStyle> {
  return target.evaluate(el => {
    const style = getComputedStyle(el);
    const probe = document.createElement("span");
    probe.style.color = "var(--kt-focus)";
    // 셸 안의 --kt-focus 재정의를 그대로 받도록 대상 옆에서 잰다.
    (el.parentElement ?? document.body).append(probe);
    const focusColor = getComputedStyle(probe).color;
    probe.remove();
    return {
      border: ["Top", "Right", "Bottom", "Left"].map(side => style.getPropertyValue(`border-${side.toLowerCase()}-width`)).join(" "),
      shadow: style.boxShadow, outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth,
      outlineOffset: style.outlineOffset, outlineColor: style.outlineColor, focusColor,
      focusVisible: el.matches(":focus-visible"),
    };
  });
}
async function tabTo(page: Page, target: Locator) {
  const handle = await target.elementHandle();
  // 매번 문서 처음(skip link)부터 Tab을 시작한다.
  await page.locator('[data-slot="admin-shell-skip-link"]').focus();
  for (let index = 0; index < 150; index += 1) {
    await page.keyboard.press("Tab");
    if (await handle!.evaluate(el => document.activeElement === el)) return;
  }
  throw new Error("Tab으로 대상 버튼에 도달하지 못했습니다.");
}
async function snap(page: Page, target: Locator, path: string) {
  const box = await target.boundingBox();
  if (!box) return;
  const pad = 8;
  await page.screenshot({ path, clip: { x: Math.max(0, box.x - pad), y: Math.max(0, box.y - pad), width: box.width + pad * 2, height: box.height + pad * 2 } });
}

for (const width of [1280, 390]) {
  test(`버튼 변형별 포커스 outline은 하나이고 hover·active·disabled에서 테두리가 굵어지지 않는다 ${width}`, async ({ browser }, info) => {
    test.setTimeout(180_000);
    const context = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await context.newPage();
    await mockApi(page);
    await login(page, "/jobs");
    const seen = new Set<string>();
    for (const path of ["/jobs/common-ui-run", "/collect", "/review", "/jobs"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      // 목록 polling 때문에 networkidle은 오지 않는다. 버튼이 그려질 때까지만 기다린다.
      await expect(page.locator('main [data-slot="button"]:visible').first()).toBeVisible();
      // 작업 상세는 실행 데이터가 온 뒤 본문 첫 줄에 재실행·삭제(destructive)가 그려진다.
      if (path === "/jobs/common-ui-run") await expect(page.locator('main [data-variant="destructive"]:visible').first()).toBeVisible();
      // 확인 대화상자 트리거(asChild)는 data-slot이 바뀌므로 data-variant로 고른다.
      const buttons = page.locator('main button[data-variant]:visible:not([disabled]), header button[data-variant]:visible:not([disabled]), [role="group"][aria-label="검수 화면 모드"] > button:visible:not([disabled])');
      const variants = await buttons.evaluateAll(nodes => nodes.map(node => node.getAttribute("data-variant") ?? "toggle"));
      for (const variant of [...new Set(variants)]) {
        if (seen.has(variant)) continue;
        seen.add(variant);
        const name = `${width}-${variant}`;
        // disabled로 바꿔도 같은 요소를 가리키도록 표식으로 고정한다.
        await buttons.and(page.locator(variant === "toggle" ? '[role="group"][aria-label="검수 화면 모드"] > button' : `[data-variant="${variant}"]`)).first().evaluate((el, id) => el.setAttribute("data-e2e-probe", id), name);
        const target = page.locator(`[data-e2e-probe="${name}"]`);
        await target.scrollIntoViewIfNeeded();
        await page.mouse.move(0, 0);
        const rest = await buttonStyle(target);
        await snap(page, target, info.outputPath(`${name}-1-rest.png`));
        await target.hover();
        const hover = await buttonStyle(target);
        expect(hover.border, `${name} hover border`).toBe(rest.border);
        expect(hover.outlineStyle, `${name} hover outline`).toBe("none");
        await snap(page, target, info.outputPath(`${name}-2-hover.png`));
        await page.mouse.move(0, 0);
        await tabTo(page, target);
        const focus = await buttonStyle(target);
        expect(focus.focusVisible, `${name} :focus-visible`).toBe(true);
        expect(focus.outlineStyle, `${name} focus outline style`).toBe("solid");
        expect(focus.outlineWidth, `${name} focus outline width`).toBe("2px");
        expect(focus.outlineOffset, `${name} focus outline offset`).toBe("2px");
        expect(focus.outlineColor, `${name} focus outline color`).toBe(focus.focusColor);
        expect(focus.border, `${name} focus border`).toBe(rest.border);
        expect(focus.shadow, `${name} focus ring`).toBe(rest.shadow);
        await snap(page, target, info.outputPath(`${name}-3-focus.png`));
        const before = await target.boundingBox();
        await target.hover();
        await page.mouse.down();
        const active = await buttonStyle(target);
        const pressed = await target.boundingBox();
        await snap(page, target, info.outputPath(`${name}-4-active.png`));
        // 클릭을 일으키지 않도록 대상 밖에서 버튼을 뗀다.
        await page.mouse.move(0, 0);
        await page.mouse.up();
        expect(active.border, `${name} active border`).toBe(rest.border);
        expect(active.shadow, `${name} active ring`).toBe(rest.shadow);
        expect(Math.abs((pressed?.y ?? 0) - (before?.y ?? 0)), `${name} active 이동`).toBeLessThanOrEqual(1);
        await target.evaluate(el => { (el as HTMLButtonElement).disabled = true; });
        const disabled = await buttonStyle(target);
        expect(disabled.border, `${name} disabled border`).toBe(rest.border);
        expect(disabled.shadow, `${name} disabled ring`).toBe(rest.shadow);
        await snap(page, target, info.outputPath(`${name}-5-disabled.png`));
        await target.evaluate(el => { (el as HTMLButtonElement).disabled = false; });
      }
    }
    for (const variant of ["default", "outline", "ghost", "destructive"]) expect([...seen], `${width} 확인한 변형`).toContain(variant);
    await context.close();
  });
}

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
  await expect(map.getByText("VWorld 지도 키 없음", { exact: true })).toBeVisible();
});

// 같은 build를 실행 env(KTC_VWORLD_BROWSER_KEY)만 다르게 띄운 두 번째 격리 UI(playwright.common-ui.config.ts).
const MAP_KEY_UI = "http://127.0.0.1:13120";
// MapLibre가 디코드할 수 있는 1x1 투명 PNG. 실제 VWorld에는 나가지 않는다.
const BLANK_TILE = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

test("지도 키는 실행 env에서 로그인한 화면으로만 오고 로그인 전 응답에는 없다(T-212)", async ({ browser, playwright }) => {
  const mapKey = process.env.KTC_COMMON_UI_MAP_KEY!;
  expect(mapKey).toMatch(/^ktc-runtime-map-key-/);
  const context = await browser.newContext({ baseURL: MAP_KEY_UI });
  const page = await context.newPage();
  await mockApi(page);
  const tileUrls: string[] = [];
  await page.route("https://api.vworld.kr/**", route => {
    tileUrls.push(route.request().url());
    return route.fulfill({ status: 200, contentType: "image/png", body: BLANK_TILE });
  });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));

  await login(page, "/");
  const map = page.getByRole("region", { name: "VWorld 지도", exact: true });
  await expect(map).toHaveAttribute("data-status", "vworld");
  await expect(map.getByText("VWorld 지도 키 없음", { exact: true })).toHaveCount(0);
  await expect.poll(() => tileUrls.length).toBeGreaterThan(0);
  // 실행 env의 키가 그대로 타일 URL에 실린다(vworld-map-core WMTS 경로).
  for (const url of tileUrls) expect(url).toContain(`/req/wmts/1.0.0/${mapKey}/Base/`);

  // 키는 인증된 HTML(RSC payload)로만 온다. 로그인 전 응답에는 없다 — 로그인 화면, 인증 redirect, 그리고
  // 동적 segment에 정적 파일 확장자를 붙인 경로(예전 proxy matcher가 인증 없이 관리자 레이아웃을 렌더하던 우회).
  const anonymous = await playwright.request.newContext({ baseURL: MAP_KEY_UI });
  try {
    const loginPage = await anonymous.get("/login");
    expect(loginPage.status()).toBe(200);
    expect((await loginPage.text()).includes(mapKey)).toBe(false);
    for (const path of ["/", "/review", "/place/x.png", "/place/1.js", "/review/1.css", "/jobs/a.map", "/review/1.svg", "/place/1.ico"]) {
      const response = await anonymous.get(path, { maxRedirects: 0 });
      expect(response.status(), `${path}는 로그인으로 보내야 한다`).toBe(307);
      expect(new URL(response.headers()["location"] ?? "", MAP_KEY_UI).pathname, path).toBe("/login");
      expect((await response.text()).includes(mapKey), `${path} 응답에 지도 키`).toBe(false);
    }
  } finally {
    await anonymous.dispose();
  }
  expect(errors).toEqual([]);
  await context.close();
});

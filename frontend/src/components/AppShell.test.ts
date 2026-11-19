// @vitest-environment jsdom

import { act, createElement, type AnchorHTMLAttributes } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  pathname: "/jobs/one", replace: vi.fn(), refresh: vi.fn(), clear: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useRouter: () => ({ replace: state.replace, refresh: state.refresh }),
}));
vi.mock("next/link", () => ({
  default: ({ children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) => createElement("a", props, children),
}));
vi.mock("@tanstack/react-query", async (original) => ({
  ...await original<typeof import("@tanstack/react-query")>(),
  useQueryClient: () => ({ clear: state.clear }),
}));
vi.mock("@/components/JobStatusLink", () => ({
  JobStatusLink: () => createElement("a", { href: "/jobs", "data-testid": "job-observer" }, "작업 상태"),
}));

import { AppShell } from "./AppShell";

let root: Root;
let host: HTMLDivElement;
let desktop = true;
const storageKey = "kor-travel-concierge:sidebar-collapsed";

async function render(title = "작업") {
  await act(async () => root.render(createElement(AppShell, {
    title, description: "진행 중인 수집", viewportLocked: true,
    actions: createElement("button", { type: "button" }, "새로고침"),
    children: createElement("p", null, "기존 본문"),
  })));
}

async function click(button: Element | null) {
  expect(button).not.toBeNull();
  await act(async () => {
    (button as HTMLElement).click();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  desktop = true;
  state.pathname = "/jobs/one";
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => setTimeout(() => callback(0), 0));
  vi.stubGlobal("cancelAnimationFrame", clearTimeout);
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: query.includes("min-width") && desktop, media: query, onchange: null,
    addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true,
  })));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("Common AdminShell 이관", () => {
  it("단일 제목/본문/동작과 기존8개 경로·중첩 작업 활성 판정을 유지한다", async () => {
    await render();
    expect([...document.querySelectorAll("h1")].map((node) => node.textContent)).toEqual(["수집 파이프라인 - 작업"]);
    expect(document.querySelectorAll('[data-slot="admin-shell-header"]')).toHaveLength(1);
    expect(document.getElementById("main-content")?.textContent).toBe("기존 본문");
    expect(document.getElementById("main-content")?.tabIndex).toBe(-1);
    expect([...document.querySelectorAll('button')].some((node) => node.textContent === "새로고침")).toBe(true);
    const links = [...document.querySelectorAll('[data-slot="app-menu-link"]')];
    expect(links.map((node) => node.getAttribute("href"))).toEqual(["/", "/collect", "/jobs", "/review", "/settings", "/status", "/dagster", "/api-test"]);
    expect(links.filter((node) => node.getAttribute("aria-current") === "page").map((node) => node.getAttribute("href"))).toEqual(["/jobs"]);
  });

  it("기존 숫자형 접힘 저장값을 읽고 같은 키/형식으로 토글한다", async () => {
    localStorage.setItem(storageKey, "1");
    await render();
    const expand = document.querySelector('button[aria-label="좌측 메뉴 펼치기"]');
    expect(expand?.getAttribute("aria-expanded")).toBe("false");
    await click(expand);
    expect(localStorage.getItem(storageKey)).toBe("0");
    expect(document.querySelector('button[aria-label="좌측 메뉴 접기"]')?.getAttribute("aria-expanded")).toBe("true");
  });

  it("모바일 drawer가 이동 시 닫히고 작업 큐 observer를 복제하지 않는다", async () => {
    desktop = false;
    await render();
    await click(document.querySelector('button[aria-label="메뉴 열기"]'));
    const dialog = document.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.contains(document.activeElement)).toBe(true);
    expect(document.querySelectorAll('[data-testid="job-observer"]')).toHaveLength(1);
    expect(dialog?.querySelector('a[href="/review"]')).not.toBeNull();
    state.pathname = "/settings";
    await render("설정");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("drawer 로그아웃도 기존POST·query정리·로그인 이동/refresh를 실행한다", async () => {
    desktop = false;
    await render();
    await click(document.querySelector('button[aria-label="메뉴 열기"]'));
    await click(document.querySelector('[role="dialog"] button[aria-label="로그아웃"]'));
    expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/auth/logout", { method: "POST" });
    expect(state.clear).toHaveBeenCalledTimes(1);
    expect(state.replace).toHaveBeenCalledWith("/login");
    expect(state.refresh).toHaveBeenCalledTimes(1);
  });
});

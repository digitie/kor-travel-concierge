import { describe, expect, it } from "vitest";

import { isNavItemActive, pickActiveNavHref } from "@/lib/nav";

const HREFS = ["/", "/collect", "/review", "/jobs", "/settings", "/status", "/api-test"];

describe("isNavItemActive", () => {
  it("루트는 정확히 일치할 때만 활성화한다", () => {
    expect(isNavItemActive("/", "/")).toBe(true);
    expect(isNavItemActive("/collect", "/")).toBe(false);
    expect(isNavItemActive("/jobs", "/")).toBe(false);
  });

  it("작업 인덱스와 작업 상세를 모두 /jobs 항목으로 활성화한다", () => {
    expect(isNavItemActive("/jobs", "/jobs")).toBe(true);
    expect(isNavItemActive("/jobs/12345", "/jobs")).toBe(true);
    expect(isNavItemActive("/jobs?attention=open", "/jobs")).toBe(false); // query는 pathname에 없음
  });

  it("상태는 자기 자신만 활성화하고 /jobs와 겹치지 않는다", () => {
    expect(isNavItemActive("/status", "/status")).toBe(true);
    expect(isNavItemActive("/jobs/1", "/status")).toBe(false);
    expect(isNavItemActive("/status", "/jobs")).toBe(false);
  });
});

describe("pickActiveNavHref", () => {
  it("작업 상세는 /jobs를 활성 href로 고른다", () => {
    expect(pickActiveNavHref("/jobs/999", HREFS)).toBe("/jobs");
  });

  it("각 경로는 자기 항목을 활성화한다", () => {
    expect(pickActiveNavHref("/", HREFS)).toBe("/");
    expect(pickActiveNavHref("/status", HREFS)).toBe("/status");
    expect(pickActiveNavHref("/review", HREFS)).toBe("/review");
    expect(pickActiveNavHref("/collect", HREFS)).toBe("/collect");
  });

  it("일치하는 항목이 없으면 undefined", () => {
    expect(pickActiveNavHref("/unknown", HREFS)).toBeUndefined();
  });
});

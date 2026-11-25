import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  parseVWorldBrowserKey,
  readVWorldBrowserKey,
  VWORLD_BROWSER_KEY_ENV,
  vworldBrowserKeyWarning,
} from "@/lib/vworld-browser-key";

const KEY = "ABCDEF01-2345-6789-ABCD-EF0123456789";

describe("브라우저 지도 키 실행 시 판정(T-212)", () => {
  it("실행 env의 KTC_VWORLD_BROWSER_KEY를 읽는다", () => {
    expect(VWORLD_BROWSER_KEY_ENV).toBe("KTC_VWORLD_BROWSER_KEY");
    expect(readVWorldBrowserKey({ KTC_VWORLD_BROWSER_KEY: KEY })).toEqual({ status: "ok", key: KEY });
    // 옛 build 입력 이름은 읽지 않는다.
    expect(readVWorldBrowserKey({ NEXT_PUBLIC_VWORLD_SERVICE_KEY: KEY })).toEqual({ status: "missing", key: "" });
  });

  it("앞뒤 공백·CR은 걷어 낸다", () => {
    expect(parseVWorldBrowserKey(`  ${KEY}\r\n`)).toEqual({ status: "ok", key: KEY });
  });

  it("빈 값·자리표시자·형식이 다른 값은 키 없음으로 본다", () => {
    expect(parseVWorldBrowserKey(undefined)).toEqual({ status: "missing", key: "" });
    expect(parseVWorldBrowserKey(" \t")).toEqual({ status: "missing", key: "" });
    for (const placeholder of ["your_vworld_browser_key_here", "your_vworld_api_key_here", "YOUR_KEY_HERE"]) {
      expect(parseVWorldBrowserKey(placeholder)).toEqual({ status: "placeholder", key: "" });
    }
    for (const bad of [`"${KEY}"`, `'${KEY}'`, `${KEY} extra`, `${KEY}/../x`, `${KEY}?a=b`]) {
      expect(parseVWorldBrowserKey(bad)).toEqual({ status: "malformed", key: "" });
    }
  });

  it(".env.example 자리표시자와 판정이 같은 값을 쓴다", () => {
    const example = readFileSync(new URL("../../../.env.example", import.meta.url), "utf8");
    const value = example.match(/^KTC_VWORLD_BROWSER_KEY=(.*)$/m)?.[1];
    expect(value).toBeTruthy();
    expect(parseVWorldBrowserKey(value).status).toBe("placeholder");
  });

  it("경고는 상태만 말하고 키 값을 싣지 않는다", () => {
    expect(vworldBrowserKeyWarning({ status: "ok", key: KEY })).toBeNull();
    for (const raw of ["", "your_vworld_browser_key_here", `"${KEY}"`]) {
      const warning = vworldBrowserKeyWarning(parseVWorldBrowserKey(raw));
      expect(warning).toMatch(/KTC_VWORLD_BROWSER_KEY/);
      expect(warning).toMatch(/VWorld 지도 키 없음/);
      expect(warning).not.toContain(KEY);
    }
    // 옛 build 입력 이름에만 값을 둔 .env를 위한 안내.
    expect(vworldBrowserKeyWarning(parseVWorldBrowserKey(""))).toMatch(/옛 이름 NEXT_PUBLIC_VWORLD_SERVICE_KEY는 더 이상 읽지 않습니다/);
  });
});

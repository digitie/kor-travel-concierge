import { describe, expect, it } from "vitest";

import {
  detectSourceInput,
  parsePlaylistId,
  parseVideoId,
  validateTargetValue,
} from "./youtube";

// backend `source_resolve.classify_source_input`과 같은 판별 결과를 보장하는 회귀 테스트.
describe("detectSourceInput", () => {
  it("재생목록 URL(list=)은 영상보다 우선한다", () => {
    expect(
      detectSourceInput("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL0123456789A"),
    ).toEqual({ kind: "playlist", value: "PL0123456789A" });
    expect(
      detectSourceInput("https://www.youtube.com/playlist?list=PLxyz012345678"),
    ).toEqual({ kind: "playlist", value: "PLxyz012345678" });
    expect(detectSourceInput("PL0123456789A")).toEqual({
      kind: "playlist",
      value: "PL0123456789A",
    });
  });

  it("영상 URL을 인식한다 (watch/youtu.be/shorts/live)", () => {
    expect(detectSourceInput("https://www.youtube.com/watch?v=dQw4w9WgXcQ")).toEqual({
      kind: "video",
      value: "dQw4w9WgXcQ",
    });
    expect(detectSourceInput("https://youtu.be/dQw4w9WgXcQ")).toEqual({
      kind: "video",
      value: "dQw4w9WgXcQ",
    });
    expect(detectSourceInput("youtube.com/shorts/dQw4w9WgXcQ")).toEqual({
      kind: "video",
      value: "dQw4w9WgXcQ",
    });
    expect(detectSourceInput("https://www.youtube.com/live/dQw4w9WgXcQ")).toEqual({
      kind: "video",
      value: "dQw4w9WgXcQ",
    });
  });

  it("bare 11자 문자열은 영상이 아니라 키워드로 본다(백엔드와 동일)", () => {
    expect(detectSourceInput("dQw4w9WgXcQ")?.kind).toBe("keyword");
  });

  it("채널 입력을 인식한다 (@handle/UC.../채널 URL)", () => {
    expect(detectSourceInput("@빵이네tv")?.kind).toBe("channel");
    expect(detectSourceInput("UC0123456789abcdefghijkl")?.kind).toBe("channel");
    expect(
      detectSourceInput("https://www.youtube.com/channel/UC0123456789abcdefghijkl")?.kind,
    ).toBe("channel");
    expect(detectSourceInput("https://www.youtube.com/@%EB%B9%B5tv")?.kind).toBe(
      "channel",
    );
    expect(detectSourceInput("https://www.youtube.com/c/SomeName")?.kind).toBe(
      "channel",
    );
  });

  it("legacy custom URL(하위 경로 포함)도 채널이다 — backend custom fallthrough와 동일", () => {
    expect(detectSourceInput("https://www.youtube.com/SomeName")?.kind).toBe(
      "channel",
    );
    expect(
      detectSourceInput("https://www.youtube.com/SomeName/videos")?.kind,
    ).toBe("channel");
  });

  it("그 외는 키워드다", () => {
    expect(detectSourceInput("부산 맛집")).toEqual({
      kind: "keyword",
      value: "부산 맛집",
    });
    expect(detectSourceInput("")).toBeNull();
    expect(detectSourceInput("   ")).toBeNull();
    // 경로가 빈 URL은 채널이 아니라 키워드(backend search fallthrough).
    expect(detectSourceInput("https://www.youtube.com/")?.kind).toBe("keyword");
  });

  it("비정상 URL(불균형 대괄호 등)은 크래시 없이 키워드로 떨어진다", () => {
    expect(detectSourceInput("[https://youtube.com")?.kind).toBe("keyword");
    expect(parsePlaylistId("[https://youtube.com/playlist?list=PL123")).toBeNull();
    expect(parseVideoId("[https://youtu.be/dQw4w9WgXcQ")).toBeNull();
  });
});

describe("parsePlaylistId / parseVideoId", () => {
  it("list= 없는 URL은 재생목록이 아니다", () => {
    expect(parsePlaylistId("https://www.youtube.com/watch?v=dQw4w9WgXcQ")).toBeNull();
  });
  it("RD(믹스) 같은 비안정 bare ID는 거부한다", () => {
    expect(parsePlaylistId("RD0123456789A")).toBeNull();
  });
  it("잘못된 영상 ID 길이는 거부한다", () => {
    expect(parseVideoId("https://youtu.be/tooshort")).toBeNull();
  });
});

describe("validateTargetValue", () => {
  it("video 유형은 URL 또는 11자 ID만 허용한다", () => {
    expect(validateTargetValue("video", "dQw4w9WgXcQ")).toBeNull();
    expect(validateTargetValue("video", "https://youtu.be/dQw4w9WgXcQ")).toBeNull();
    expect(validateTargetValue("video", "부산 맛집")).not.toBeNull();
  });
  it("playlist 유형은 list= URL 또는 PL... ID만 허용한다", () => {
    expect(validateTargetValue("playlist", "PL0123456789A")).toBeNull();
    expect(validateTargetValue("playlist", "부산 맛집")).not.toBeNull();
  });
  it("keyword/channel/auto는 자유 입력을 허용한다", () => {
    expect(validateTargetValue("keyword", "부산 맛집")).toBeNull();
    expect(validateTargetValue("channel", "빵이네tv")).toBeNull();
    expect(validateTargetValue("auto", "아무 텍스트")).toBeNull();
  });
  it("빈 입력은 거부한다", () => {
    expect(validateTargetValue("auto", "  ")).not.toBeNull();
  });
});

import { describe, expect, it } from "vitest";

import {
  timestampedVideoUrl,
  timestampToSeconds,
  youtubeWatchUrl,
} from "./format";

describe("timestampToSeconds", () => {
  it.each([
    ["00:12", 12],
    ["12:34", 754],
    ["01:02:03", 3723],
    ["123:45", 7425],
    ["12:34-13:00", 754],
    ["[01:02:03] ~ 01:03:00", 3723],
  ])("%s의 첫 시각을 초로 변환한다", (value, expected) => {
    expect(timestampToSeconds(value)).toBe(expected);
  });

  it.each([
    null,
    "",
    "abc",
    "-1:00",
    "00:61-01:00",
    "99:99-12:34",
    "12:34:99",
    "1:60:00",
    "1:2",
    "[12:34",
    "12:34]",
  ])(
    "%s는 유효하지 않은 시각으로 거절한다",
    (value) => {
      expect(timestampToSeconds(value)).toBeNull();
    },
  );
});

describe("timestampedVideoUrl", () => {
  it("기존 query와 hash를 보존하고 t를 갱신한다", () => {
    expect(
      timestampedVideoUrl(
        "https://www.youtube.com/watch?v=abc&list=xyz&t=1s#chapter",
        "01:02-01:05",
      ),
    ).toBe("https://www.youtube.com/watch?v=abc&list=xyz&t=62s#chapter");
  });

  it("시각이나 URL이 잘못되면 원본 URL을 보존한다", () => {
    expect(timestampedVideoUrl("https://youtu.be/abc", "invalid")).toBe(
      "https://youtu.be/abc",
    );
    expect(timestampedVideoUrl("not-a-url", "00:10")).toBe("not-a-url");
  });

  it("video ID를 URLSearchParams로 인코딩한다", () => {
    expect(youtubeWatchUrl("abc&list=wrong", "00:00")).toBe(
      "https://www.youtube.com/watch?v=abc%26list%3Dwrong&t=0s",
    );
  });
});

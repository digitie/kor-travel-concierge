import { describe, expect, it } from "vitest";

import {
  approximateTranscriptEvidenceScrollTop,
  cleanTranscript,
  normalizeTranscriptTimestampNeedle,
} from "./transcript";

describe("cleanTranscript", () => {
  it("timestamp prefix와 지원하는 비언어 표식을 제거하고 빈 줄을 합친다", () => {
    const transcript = [
      "  [1:02] 첫 문장  ",
      "01:03 [음악] 두 번째 문장",
      "[01:02:03] [Music]",
      "   ",
      "12:34 [박수] 마지막 [웃음]",
    ].join("\r\n");

    expect(cleanTranscript(transcript)).toBe(
      "첫 문장\n두 번째 문장\n마지막",
    );
  });

  it("빈 원문은 빈 문자열로 유지한다", () => {
    expect(cleanTranscript("")).toBe("");
    expect(cleanTranscript("\n  \r\n")).toBe("");
  });
});

describe("normalizeTranscriptTimestampNeedle", () => {
  it.each([
    [null, null],
    ["", null],
    ["1:02", "01:02"],
    ["1:02:03", "01:02:03"],
    ["00:09", "00:09"],
    ["chapter", "chapter"],
  ] as const)("%s 문자열을 기존 검색 needle로 변환한다", (value, expected) => {
    expect(normalizeTranscriptTimestampNeedle(value)).toBe(expected);
  });
});

describe("approximateTranscriptEvidenceScrollTop", () => {
  it("정규화한 timestamp의 문자 위치 비율로 기존 근사 scrollTop을 계산한다", () => {
    const transcript = `00:00 ${"시작 문장 ".repeat(20)}\n02:10 대상 근거`;
    const index = transcript.indexOf("02:10");
    const expected = Math.max(0, 1_200 * (index / transcript.length) - 40);

    expect(
      approximateTranscriptEvidenceScrollTop(transcript, "2:10", 1_200),
    ).toBeCloseTo(expected, 10);
  });

  it.each([
    ["", "00:10"],
    ["00:00 시작", null],
    ["00:00 시작", ""],
    ["00:00 시작", "10:00"],
  ] as const)(
    "원문 또는 검색 needle이 없으면 시작 위치를 반환한다",
    (transcript, timestamp) => {
      expect(
        approximateTranscriptEvidenceScrollTop(transcript, timestamp, 1_200),
      ).toBe(0);
    },
  );

  it("timestamp가 원문 첫 문자에 있으면 상단 여백 계산을 0으로 제한한다", () => {
    expect(
      approximateTranscriptEvidenceScrollTop("00:10 시작", "00:10", 1_200),
    ).toBe(0);
  });
});

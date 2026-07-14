const TRANSCRIPT_EVIDENCE_TOP_OFFSET_PX = 40;

/** 자막 표시에서 timestamp prefix와 제한된 비언어 표식을 제거한다. */
export function cleanTranscript(text: string): string {
  return text
    .split(/\r?\n/)
    .map((line) =>
      line
        .replace(
          /^\s*(?:\[\d{1,2}:\d{2}(?::\d{2})?\]|\d{1,2}:\d{2}(?::\d{2})?)\s*/g,
          "",
        )
        .replace(/\[(?:음악|Music|music|박수|웃음)\]/g, "")
        .trim(),
    )
    .filter(Boolean)
    .join("\n");
}

/** 기존 자막 검색과 동일하게 colon 구간을 두 자리로 맞춘 검색 문자열을 만든다. */
export function normalizeTranscriptTimestampNeedle(
  value: string | null,
): string | null {
  if (!value) return null;
  const parts = value.split(":").map((part) => part.padStart(2, "0"));
  return parts.join(":");
}

/**
 * timestamp segment별 DOM 위치가 없으므로 원문 문자 index 비율을 전체 scrollHeight에
 * 선형 환산한다. 정확한 line anchor가 아니라 기존 동작을 보존하는 근사치다.
 */
export function approximateTranscriptEvidenceScrollTop(
  transcriptText: string,
  evidenceTimestamp: string | null,
  scrollHeight: number,
): number {
  const needle = normalizeTranscriptTimestampNeedle(evidenceTimestamp);
  const index = needle ? transcriptText.indexOf(needle) : -1;
  if (index < 0) return 0;
  const ratio = index / Math.max(transcriptText.length, 1);
  return Math.max(
    0,
    scrollHeight * ratio - TRANSCRIPT_EVIDENCE_TOP_OFFSET_PX,
  );
}

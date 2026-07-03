// 날짜·시간·용량·간격 공용 포맷터. 화면마다 복붙되던 사본을 단일 출처로 모은다.

/** ko-KR 날짜+시간 (연-월-일 시:분). 값 없음/비정상은 "-" */
export function formatDateTime(value: string | null | undefined): string {
  const date = toDate(value);
  if (!date) return "-";
  return date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** ko-KR 월-일 시:분 (연도 생략, 촘촘한 표 셀용). 값 없음/비정상은 "-" */
export function formatDateTimeShort(value: string | null | undefined): string {
  const date = toDate(value);
  if (!date) return "-";
  return date.toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** ko-KR 날짜(연-월-일). 값 없음/비정상은 "-" */
export function formatDate(value: string | null | undefined): string {
  const date = toDate(value);
  if (!date) return "-";
  return date.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

/** ko-KR 시:분 (같은 날 반복 실행 표시용). 값 없음/비정상은 "-" */
export function formatTime(value: string | null | undefined): string {
  const date = toDate(value);
  if (!date) return "-";
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

/** 바이트 → 사람이 읽는 용량 문자열 */
export function formatBytes(bytes: number | undefined): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/** 분 단위 반복 간격 → 한국어 라벨(달/주일/일/시간/분) */
export function intervalLabel(minutes: number | null | undefined): string {
  if (!minutes) return "-";
  if (minutes % 43200 === 0) return `${minutes / 43200}달`;
  if (minutes % 10080 === 0) return `${minutes / 10080}주일`;
  if (minutes % 1440 === 0) return `${minutes / 1440}일`;
  if (minutes % 60 === 0) return `${minutes / 60}시간`;
  return `${minutes}분`;
}

/** 초 → "N분 M초" */
export function durationLabel(seconds: number | null | undefined): string {
  if (seconds == null) return "-";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}분 ${s}초` : `${s}초`;
}

export function asNum(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

export function asRecord(value: unknown): Record<string, number> {
  return value && typeof value === "object"
    ? (value as Record<string, number>)
    : {};
}

function toDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

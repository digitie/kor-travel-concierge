export function runStateLabel(state: string | null | undefined): string {
  const key = normalizeKey(state);
  const labels: Record<string, string> = {
    pending: "대기",
    running: "실행",
    done: "완료",
    failed: "실패",
    cancelled: "취소",
    canceled: "취소",
    stale: "지연",
  };
  return labels[key] ?? fallbackLabel(state, "상태 없음");
}

// 작업 상태 → Badge variant. 상태 색 규칙 단일 출처(CollectWorkspace/StatusDashboard/JobLog 공용).
export function runStateBadgeVariant(
  state: string | null | undefined,
): "outline" | "secondary" | "destructive" {
  const key = normalizeKey(state);
  if (key === "failed") return "destructive";
  if (key === "running" || key === "done") return "secondary";
  return "outline";
}

// 작업 상태 → 진행률 bar 색 클래스(공용).
export function runProgressBarClass(state: string | null | undefined): string {
  const key = normalizeKey(state);
  if (key === "failed") return "h-full rounded-full bg-destructive";
  if (key === "done") return "h-full rounded-full bg-success";
  return "h-full rounded-full bg-primary";
}

export function candidateStatusLabel(status: string | null | undefined): string {
  const key = normalizeKey(status);
  const labels: Record<string, string> = {
    needs_review: "검수 대기",
    pending: "검수 대기",
    matched: "확정",
    confirmed: "확정",
    user_corrected: "수정 확정",
    auto_matched: "자동 확정",
    rejected: "제외",
    ignored: "제외",
    deleted: "삭제",
  };
  return labels[key] ?? fallbackLabel(status, "상태 없음");
}

export function categoryDisplayLabel(value: string | null | undefined): string {
  const key = normalizeKey(value);
  if (!key || key === "0" || key === "unknown" || key === "none") {
    return "미분류";
  }
  return value?.trim() || "미분류";
}

export function jobTypeDisplayLabel(type: string | null | undefined): string {
  const key = normalizeKey(type);
  const labels: Record<string, string> = {
    harvest: "수집",
    source_scan: "예약 스캔",
    video_analysis: "영상 분석",
    deep_research: "심층 조사",
    transcript: "자막",
    poi_batch: "장소 추출",
    geocode: "지오코딩",
    postprocess: "후처리",
  };
  return labels[key] ?? fallbackLabel(type, "작업");
}

export function targetTypeDisplayLabel(type: string | null | undefined): string {
  const key = normalizeKey(type);
  const labels: Record<string, string> = {
    channel: "유튜버",
    playlist: "재생목록",
    keyword: "검색어",
    video: "영상",
    auto: "자동",
  };
  return labels[key] ?? fallbackLabel(type, "대상");
}

export function loginEventLabel(value: string | null | undefined): string {
  const key = normalizeKey(value);
  const labels: Record<string, string> = {
    login: "로그인",
    logout: "로그아웃",
  };
  return labels[key] ?? fallbackLabel(value, "기록");
}

export function loginOutcomeLabel(value: string | null | undefined): string {
  const key = normalizeKey(value);
  const labels: Record<string, string> = {
    succeeded: "성공",
    failed: "실패",
    denied: "거부",
  };
  return labels[key] ?? fallbackLabel(value, "결과 없음");
}

export function assetTypeLabel(value: string | null | undefined): string {
  const key = normalizeKey(value);
  const labels: Record<string, string> = {
    raw_video: "원본",
    subtitles: "자막",
    subtitle: "자막",
    transcript: "전사",
    transcripts: "전사",
    frame: "프레임",
    frames: "프레임",
  };
  return labels[key] ?? fallbackLabel(value, "자산");
}

function normalizeKey(value: string | null | undefined): string {
  return (value ?? "").trim().toLowerCase().replaceAll("-", "_");
}

function fallbackLabel(value: string | null | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed.replaceAll("_", " ") : fallback;
}

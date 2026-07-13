import type {
  CrawlRunSummary,
  ReviewGroundingStatus,
  RunAttention,
  RunOutcome,
} from "./api";

const HIGH_PRIORITY_QUEUE_REASONS = new Set([
  "ungrounded",
  "name_mismatch",
  "region_mismatch",
  "source_conflict",
  "source_low_confidence",
  "source_uncertain",
]);

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

export function isTerminalRun(state: string | null | undefined): boolean {
  const key = normalizeKey(state);
  return key === "done" || key === "failed" || key === "cancelled";
}

export function runOutcome(
  run: Pick<CrawlRunSummary, "state" | "result">,
): RunOutcome {
  const state = normalizeKey(run.state);
  if (state === "done") {
    return run.result?.quota_deferred === true
      ? "quota_deferred"
      : "succeeded";
  }
  if (state === "failed") return "failed";
  if (state === "cancelled") return "cancelled";
  return "active";
}

export function runOutcomeLabel(
  run: Pick<CrawlRunSummary, "state" | "result">,
): string {
  const labels: Record<RunOutcome, string> = {
    active: runStateLabel(run.state),
    succeeded: "완료",
    quota_deferred: "쿼터 보류",
    failed: "실패",
    cancelled: "취소",
  };
  return labels[runOutcome(run)];
}

export function runOutcomeBadgeVariant(
  run: Pick<CrawlRunSummary, "state" | "result">,
): "outline" | "secondary" | "destructive" {
  const outcome = runOutcome(run);
  if (outcome === "failed" || outcome === "quota_deferred") {
    return "destructive";
  }
  if (outcome === "succeeded") return "secondary";
  return "outline";
}

export function runAttentionLabel(
  attention: RunAttention | null | undefined,
): string {
  const labels: Record<RunAttention, string> = {
    open: "확인 필요",
    acknowledged: "확인함",
    superseded: "재시작됨",
    resolved: "해결됨",
  };
  return attention ? labels[attention] : "주의 없음";
}

export function runAttentionBadgeVariant(
  attention: RunAttention | null | undefined,
): "outline" | "secondary" | "destructive" {
  if (attention === "open") return "destructive";
  if (attention === "superseded" || attention === "resolved") {
    return "secondary";
  }
  return "outline";
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

export function runOutcomeProgressBarClass(
  run: Pick<CrawlRunSummary, "state" | "result">,
): string {
  if (runOutcome(run) === "quota_deferred") {
    return "h-full rounded-full bg-warning";
  }
  return runProgressBarClass(run.state);
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

export function queueReasonLabel(reason: string | null | undefined): string {
  const key = normalizeKey(reason);
  const labels: Record<string, string> = {
    ungrounded: "원문 근거 미확인",
    name_mismatch: "장소명 불일치",
    region_mismatch: "지역 불일치",
    source_conflict: "출처 간 충돌",
    source_low_confidence: "출처 대조 신뢰도 낮음",
    source_uncertain: "출처 대조 불확실",
    ambiguous: "후보 모호",
    no_result: "검색 결과 없음",
    vworld_unrefined_single: "VWorld 미정제 단일 결과",
    foreign: "해외 후보",
    description_only: "설명문 전용",
    visual_only: "시각 근거 전용",
    provider_missing: "provider 근거 누락",
    extraction_only: "추출 직후",
  };
  return labels[key] ?? fallbackLabel(reason, "사유 없음");
}

export function queueReasonBadgeVariant(
  reason: string | null | undefined,
): "secondary" | "destructive" {
  return HIGH_PRIORITY_QUEUE_REASONS.has(normalizeKey(reason))
    ? "destructive"
    : "secondary";
}

export function sourceKindLabel(source: string | null | undefined): string {
  const key = normalizeKey(source);
  const labels: Record<string, string> = {
    transcript: "자막",
    url_summary: "영상 URL 요약",
    reconcile: "출처 대조",
    manual: "사용자 입력",
    geocoding: "지오코딩",
    description: "영상 설명",
    visual: "영상 프레임",
  };
  return labels[key] ?? fallbackLabel(source, "출처 없음");
}

export function groundingStatusLabel(
  status: string | null | undefined,
): string {
  const key = normalizeKey(status);
  const labels: Record<ReviewGroundingStatus, string> = {
    verified_raw: "원문 근거 확인",
    unverified: "원문 근거 불일치",
    missing: "원문 근거 없음",
    not_applicable: "원문 대조 비대상",
    legacy_unknown: "기존 데이터 미확인",
  };
  return key in labels
    ? labels[key as ReviewGroundingStatus]
    : fallbackLabel(status, "근거 상태 없음");
}

export function groundingStatusBadgeVariant(
  status: ReviewGroundingStatus,
): "outline" | "secondary" | "destructive" {
  if (status === "unverified" || status === "missing") return "destructive";
  if (status === "verified_raw") return "secondary";
  return "outline";
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

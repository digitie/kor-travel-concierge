// `/jobs` 이력 테이블(T-192)이 기존 `/runs` 계약(terminal·user_jobs_only·job_types·
// attention·state)을 **소비**하기 위한 파라미터 매핑. 필터·pagination·total은 backend가
// 이미 제공하므로 여기서는 UI 필터 값을 그 계약으로 변환만 한다(재구현 금지).

import type { RunAttention } from "@/lib/api";

export const JOB_HISTORY_STATE_ALL = "all" as const;
export const JOB_HISTORY_TYPE_ALL = "all" as const;

/** 이력은 종료(terminal) 작업만 보여주므로 상태 필터는 종료 상태만 제공한다. */
export const JOB_HISTORY_STATE_OPTIONS = [
  { value: JOB_HISTORY_STATE_ALL, label: "전체" },
  { value: "done", label: "완료" },
  { value: "failed", label: "실패" },
  { value: "cancelled", label: "취소" },
] as const;

export type JobHistoryFilters = {
  attentionOnly: boolean;
  state: string;
  jobType: string;
};

export type RunHistoryParams = {
  terminal: true;
  attention?: RunAttention;
  userJobsOnly?: boolean;
  jobTypes?: string[];
  state?: string;
};

/**
 * UI 필터 → `listRunsPage` 파라미터. `user_jobs_only`와 `job_types`는 backend에서
 * 함께 쓸 수 없으므로(400), 유형=전체면 서버 정본 사용자 작업 유형을, 특정 유형이면
 * 그 유형만 조회한다.
 */
export function buildRunHistoryParams(
  filters: JobHistoryFilters,
): RunHistoryParams {
  const params: RunHistoryParams = { terminal: true };
  if (filters.attentionOnly) {
    params.attention = "open";
  }
  if (filters.state && filters.state !== JOB_HISTORY_STATE_ALL) {
    params.state = filters.state;
  }
  if (filters.jobType && filters.jobType !== JOB_HISTORY_TYPE_ALL) {
    params.jobTypes = [filters.jobType];
  } else {
    params.userJobsOnly = true;
  }
  return params;
}

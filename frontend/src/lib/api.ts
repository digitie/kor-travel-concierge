// 브라우저는 항상 same-origin Next BFF(`/api/v1/*` Route Handler)로 요청한다.
// Route Handler가 서버 사이드에서 백엔드로 프록시하며 인증 코드(`X-API-Key`)를
// 주입하므로 브라우저 번들에는 API 키를 노출하지 않는다(ADR-24).
// 기본값은 빈 문자열(상대 경로)이다.
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(
  /\/$/,
  "",
);

// VWorld 지도 서비스 키 (브라우저 직접 로드).
export const VWORLD_SERVICE_KEY =
  process.env.NEXT_PUBLIC_VWORLD_SERVICE_KEY ?? "";

export type HarvestTargetType =
  | "auto"
  | "keyword"
  | "channel"
  | "playlist"
  | "video";
export type HarvestContentFilter = "both" | "shorts" | "videos";
export type DestinationSort = "latest" | "mention_count" | "name" | "category";
export type DestinationExportFormat = "xlsx" | "gpx" | "kml";

export type StartHarvestInput = {
  targetType: HarvestTargetType;
  targetValue: string;
  maxVideos: number;
  // true면 영상 수집만 하고 자막 생성은 건너뛴다(자막 전 확인 게이팅).
  skipTranscript?: boolean;
  // 설정하면 해당 분 간격으로 반복 수집(source_target 등록).
  repeatIntervalMinutes?: number | null;
  // 반복 횟수(0이면 무한). repeatIntervalMinutes가 있을 때만 의미.
  repeatMaxRuns?: number | null;
  // 콘텐츠 유형 필터: both(숏츠+동영상)/shorts(숏츠만)/videos(동영상만).
  contentFilter?: HarvestContentFilter;
  // true면 강제 다운로드(증분 워터마크 무시, 처음부터 재수집).
  force?: boolean;
  // 카테고리 매칭 실패 시 쓸 기본 카테고리 코드(unknown=0).
  defaultCategoryCode?: string | null;
};

export type SourceTargetSummary = {
  id: number;
  target_type: HarvestTargetType | string;
  source_value: string;
  display_name: string | null;
  target_type_label?: string | null;
  target_label?: string | null;
  is_active: boolean;
  scan_interval_minutes: number | null;
  max_runs: number;
  max_videos: number | null;
  default_category_code: string | null;
  default_category_label: string | null;
  run_count: number;
  next_crawl_at: string | null;
  last_crawled_at: string | null;
  last_scan_at: string | null;
  last_seen_video_published_at: string | null;
  scan_failure_count: number;
  last_scan_error: string | null;
  created_at: string | null;
};

export type HarvestJob = {
  job_id: string;
  state: string;
};

export type HarvestStatus = {
  job_id: string;
  state: "pending" | "running" | "done" | "failed" | string;
  progress: number;
  current_message: string | null;
  status_logs: RunStatusLog[];
  last_error: string | null;
  result: Record<string, unknown> | null;
};

export type RunStatusLog = {
  timestamp: string;
  level: "info" | "success" | "warning" | "error" | string;
  message: string;
  progress: number | null;
};

export type DestinationSummary = {
  place_id: number;
  name: string;
  description?: string | null;
  gemini_enriched_description?: string | null;
  latitude: number;
  longitude: number;
  category: string | null;
  category_code_suggestion?: string | null;
  sigungu_code?: string | null;
  sigungu_name?: string | null;
  legal_dong_code?: string | null;
  legal_dong_name?: string | null;
  official_address: string | null;
  road_address?: string | null;
  is_geocoded: boolean;
  mention_count: number;
  source_channel_count: number;
  source_videos: PlaceSourceVideo[];
};

export type PlaceSourceVideo = {
  mapping_id: number;
  video_id: string;
  video_title: string;
  video_url: string;
  channel_id: string;
  channel_name: string | null;
  timestamp_start: string | null;
  timestamp_end: string | null;
  ai_summary: string;
  speaker_note: string | null;
};

export type UnmatchedCandidate = {
  id: number;
  video_id: string;
  ai_place_name: string;
  location_hint: string | null;
  candidate_category: string | null;
  candidate_category_code: string | null;
  match_status: string;
  timestamp_start: string | null;
  // POI 추출 LLM의 국내 여부 판정. null=미판정, true=국내, false=해외.
  is_domestic: boolean | null;
};

export type CrawlRunSummary = {
  job_id: string;
  job_type: string;
  source: string;
  target_type: string | null;
  target_id: string | null;
  // 사람이 읽을 수 있는 라벨(백엔드가 채움). 없으면 프런트에서 원시값으로 폴백.
  target_type_label?: string | null;
  target_label?: string | null;
  job_type_label?: string | null;
  state: string;
  progress: number;
  current_message: string | null;
  // 입력 payload의 최대 영상 수(진행 중에도 노출). result가 아니라 payload 출처.
  max_videos?: number | null;
  default_category_code?: string | null;
  default_category_label?: string | null;
  status_logs: RunStatusLog[];
  retry_count: number;
  last_error: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

// 사용자에게 노출하는 작업 유형(내부 source_scan 등은 기본 제외).
export const USER_JOB_TYPES = [
  "harvest",
  "poi_batch",
  "deep_research",
  "video_analysis",
] as const;

export type AuditLogSummary = {
  id: number;
  actor_type: string;
  action: string;
  target_type: string;
  target_id: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
};

export type RustfsAssetSummary = {
  asset_type: string;
  count: number;
  size_bytes: number;
};

export type RustfsStatus = {
  enabled: boolean;
  endpoint: string;
  console_url: string;
  retention_policy: string;
  health: {
    ok: boolean;
    url: string;
    status_code: number | null;
    error: string | null;
  };
  assets: RustfsAssetSummary[];
};

export type RuntimeSettings = {
  // gemini_engine_version은 선택된 AI 엔진(Gemini 또는 DeepSeek)을 가리킨다.
  gemini_engine_version: string;
  gemini_engine_default: string;
  // Gemini + DeepSeek 통합 엔진 선택지.
  gemini_engine_options: string[];
  // 모든 AI 프롬프트 앞에 붙는 사전 프롬프트(미설정 시 기본 예제).
  ai_preprompt: string;
  ai_preprompt_default: string;
  // DeepSeek 키는 평문으로 내려주지 않고 설정 여부만 노출한다.
  deepseek_api_key_set: boolean;
  // 각 API 키의 설정 여부(값은 내려주지 않는다). DB→.env 순으로 판정.
  api_keys?: Record<string, { set: boolean }>;
};

// UI에서 관리하는 API 키 이름(라벨은 컴포넌트에서 매핑).
export const API_KEY_NAMES = [
  "youtube_api_key",
  "gemini_api_key",
  "google_places_api_key",
  "naver_search_client_id",
  "naver_search_client_secret",
  "kakao_rest_api_key",
  "vworld_service_key",
  "kor_travel_geo_v2_api_key",
  "deepseek_api_key",
] as const;
export type ApiKeyName = (typeof API_KEY_NAMES)[number];

// 변경된 필드만 보낸다. 키는 새 값을 입력했을 때만 포함한다(빈 값은 미변경).
export type RuntimeSettingsUpdate = {
  gemini_engine_version?: string;
  ai_preprompt?: string;
  deepseek_api_key?: string;
  youtube_api_key?: string;
  gemini_api_key?: string;
  google_places_api_key?: string;
  naver_search_client_id?: string;
  naver_search_client_secret?: string;
  kakao_rest_api_key?: string;
  vworld_service_key?: string;
  kor_travel_geo_v2_api_key?: string;
};

export type PublicApiKeySummary = {
  id: number;
  label: string | null;
  key_hint: string;
  state: "active" | "revoked" | string;
  created_at: string;
  created_by: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
};

export type PublicApiKeyCreateResponse = {
  key: string;
  item: PublicApiKeySummary;
};

export type LoginEventSummary = {
  id: number;
  event_type: "login" | "logout" | string;
  outcome: "succeeded" | "failed" | "denied" | string;
  attempted_username: string | null;
  reason: string | null;
  client_ip: string | null;
  user_agent: string | null;
  next_path: string | null;
  created_at: string;
};

export type ResolveCandidateInput = {
  action: "match_existing" | "create_place" | "ignore";
  placeId?: number;
  correctedName?: string;
  latitude?: number;
  longitude?: number;
  officialAddress?: string;
  roadAddress?: string;
  category?: string;
  // 드롭다운으로 강제하는 8자리 카탈로그 코드(있으면 category를 label로 덮어씀).
  categoryCode?: string;
  reviewNote?: string;
};

export type CategoryOption = {
  code: string;
  label: string;
  depth: number | null;
  tier1_name: string | null;
};

function harvestPayload(input: StartHarvestInput) {
  return {
    query: input.targetType === "keyword" ? input.targetValue : undefined,
    channel_id: input.targetType === "channel" ? input.targetValue : undefined,
    playlist_id: input.targetType === "playlist" ? input.targetValue : undefined,
    video_id: input.targetType === "video" ? input.targetValue : undefined,
    // 자동: 링크/검색어를 그대로 보내면 백엔드가 종류를 판별한다.
    auto_input: input.targetType === "auto" ? input.targetValue : undefined,
    max_videos: input.maxVideos,
    skip_transcript: input.skipTranscript ?? false,
    repeat_interval_minutes: input.repeatIntervalMinutes ?? undefined,
    repeat_max_runs: input.repeatMaxRuns ?? undefined,
    content_filter: input.contentFilter ?? "both",
    // 강제 다운로드: 증분 워터마크를 무시하고 처음부터 다시 수집.
    force: input.force ?? false,
    default_category_code: input.defaultCategoryCode ?? undefined,
  };
}

// 백엔드 요청 공통 헤더. 인증 코드(`X-API-Key`)는 브라우저가 아니라 same-origin BFF
// Route Handler가 서버 사이드에서 주입한다(ADR-24). 브라우저는 키를 보유하지 않는다.
function buildHeaders(extra: HeadersInit = {}): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  return { ...headers, ...(extra as Record<string, string>) };
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: buildHeaders(init.headers),
  });
  if (!response.ok) {
    if (
      response.status === 401 &&
      typeof window !== "undefined" &&
      window.location.pathname !== "/login"
    ) {
      const next = `${window.location.pathname}${window.location.search}`;
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
    }
    const body = await response.text();
    const message = body.length > 240 ? `${body.slice(0, 240)}...` : body;
    throw new Error(
      message
        ? `API 요청 실패(${response.status}): ${message}`
        : `API 요청 실패(${response.status})`,
    );
  }
  return (await response.json()) as T;
}

export async function startHarvest(input: StartHarvestInput): Promise<HarvestJob> {
  return requestJson<HarvestJob>("/api/v1/harvest", {
    method: "POST",
    body: JSON.stringify(harvestPayload(input)),
  });
}

export async function triggerPoiBatch(): Promise<{
  enqueued_jobs: number;
  videos: number;
  job_ids: string[];
}> {
  return requestJson("/api/v1/jobs/poi-batch", { method: "POST" });
}

export async function getHarvestStatus(jobId: string): Promise<HarvestStatus> {
  return requestJson<HarvestStatus>(`/api/v1/harvest/${jobId}`);
}

export async function startTranscript(jobId: string): Promise<HarvestJob> {
  return requestJson<HarvestJob>(`/api/v1/harvest/${jobId}/transcript`, {
    method: "POST",
  });
}

export type DestinationGroupDim = "none" | "channel" | "playlist" | "keyword";

export type DestinationFilter = {
  channelId?: string | null;
  playlistId?: string | null;
  keyword?: string | null;
  videoId?: string | null;
  category?: string | null;
  query?: string | null;
  district?: string | null;
};

export type DestinationFacets = {
  channels: { id: string; title: string; place_count: number }[];
  playlists: { id: string; title: string; place_count: number }[];
  keywords: { value: string; place_count: number }[];
  categories: { value: string; place_count: number }[];
  districts: { value: string; label: string; place_count: number }[];
};

export async function listDestinations(
  sort: DestinationSort = "latest",
  filter?: DestinationFilter,
): Promise<DestinationSummary[]> {
  const params = new URLSearchParams({ sort });
  if (filter?.channelId) params.set("channel_id", filter.channelId);
  if (filter?.playlistId) params.set("playlist_id", filter.playlistId);
  if (filter?.keyword) params.set("keyword", filter.keyword);
  if (filter?.videoId) params.set("video_id", filter.videoId);
  if (filter?.category) params.set("category", filter.category);
  if (filter?.query) params.set("q", filter.query);
  if (filter?.district) params.set("district", filter.district);
  return requestJson<DestinationSummary[]>(
    `/api/v1/destinations?${params.toString()}`,
  );
}

// 결과 보기 그룹화용 출처 facet(유튜버/재생목록/검색어별 장소 수).
export async function listDestinationFacets(): Promise<DestinationFacets> {
  return requestJson<DestinationFacets>("/api/v1/destinations/facets");
}

export function buildDestinationExportUrl({
  format,
  placeIds,
  sort = "mention_count",
}: {
  format: DestinationExportFormat;
  placeIds: number[];
  sort?: DestinationSort;
}) {
  const params = new URLSearchParams({ format, sort });
  if (placeIds.length > 0) {
    params.set("ids", placeIds.join(","));
  }
  return `${API_BASE_URL}/api/v1/destinations/export?${params.toString()}`;
}

export async function listUnmatchedCandidates(
  filter?: DestinationFilter,
): Promise<UnmatchedCandidate[]> {
  const params = new URLSearchParams();
  if (filter?.channelId) params.set("channel_id", filter.channelId);
  if (filter?.playlistId) params.set("playlist_id", filter.playlistId);
  if (filter?.keyword) params.set("keyword", filter.keyword);
  const qs = params.toString();
  return requestJson<UnmatchedCandidate[]>(
    `/api/v1/destinations/unmatched${qs ? `?${qs}` : ""}`,
  );
}

export type ReprocessStage = "transcript" | "correction" | "poi";

// 검수에서 선택한 영상들을 지정 단계부터 다시 처리(자막/교정/POI). 장바구니 재처리.
export async function reprocessVideos(
  videoIds: string[],
  startStage: ReprocessStage,
): Promise<{
  enqueued_jobs: number;
  videos: number;
  job_ids: string[];
  start_stage: ReprocessStage;
}> {
  return requestJson("/api/v1/destinations/reprocess", {
    method: "POST",
    body: JSON.stringify({ video_ids: videoIds, start_stage: startStage }),
  });
}

// 검수에서 관련 없거나 질 낮은 동영상을 제외(삭제) — 관련 POI 삭제 + 이후 수집 스킵.
export async function excludeVideo(
  videoId: string,
  reason?: string,
): Promise<{
  video_id: string;
  deleted_candidates: number;
  deleted_mappings: number;
  deleted_places: number;
}> {
  return requestJson(
    `/api/v1/destinations/videos/${encodeURIComponent(videoId)}/exclude`,
    {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    },
  );
}

export async function listRuns({
  state,
  limit = 12,
  jobTypes,
}: {
  state?: "pending" | "running" | "done" | "failed" | string;
  limit?: number;
  jobTypes?: readonly string[];
} = {}): Promise<CrawlRunSummary[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (state) {
    params.set("state", state);
  }
  if (jobTypes && jobTypes.length > 0) {
    params.set("job_types", jobTypes.join(","));
  }
  return requestJson<CrawlRunSummary[]>(`/api/v1/runs?${params.toString()}`);
}

export async function listRunQueue(
  jobTypes?: readonly string[],
): Promise<CrawlRunSummary[]> {
  const [running, pending] = await Promise.all([
    listRuns({ state: "running", limit: 50, jobTypes }),
    listRuns({ state: "pending", limit: 50, jobTypes }),
  ]);
  return [
    ...running.sort(compareRunIdAsc),
    ...pending.sort(compareRunIdAsc),
  ];
}

export async function runSourceTargetNow(
  id: number,
  force = false,
): Promise<HarvestJob> {
  const qs = force ? "?force=true" : "";
  return requestJson<HarvestJob>(`/api/v1/source-targets/${id}/run-now${qs}`, {
    method: "POST",
  });
}

function compareRunIdAsc(a: CrawlRunSummary, b: CrawlRunSummary) {
  return Number(a.job_id) - Number(b.job_id);
}

export async function listAuditLogs(): Promise<AuditLogSummary[]> {
  return requestJson<AuditLogSummary[]>("/api/v1/audit-logs?limit=10");
}

export async function getRustfsStatus(): Promise<RustfsStatus> {
  return requestJson<RustfsStatus>("/api/v1/storage/rustfs");
}

export async function getRuntimeSettings(): Promise<RuntimeSettings> {
  return requestJson<RuntimeSettings>("/api/v1/settings");
}

export async function updateRuntimeSettings(
  input: RuntimeSettingsUpdate,
): Promise<{ status: string; settings: RuntimeSettings }> {
  return requestJson<{ status: string; settings: RuntimeSettings }>("/api/v1/settings", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listPublicApiKeys(): Promise<PublicApiKeySummary[]> {
  return requestJson<PublicApiKeySummary[]>("/api/v1/admin/public-api-keys");
}

export async function createPublicApiKey(
  label?: string,
): Promise<PublicApiKeyCreateResponse> {
  return requestJson<PublicApiKeyCreateResponse>("/api/v1/admin/public-api-keys", {
    method: "POST",
    body: JSON.stringify({ label: label?.trim() || null }),
  });
}

export async function revokePublicApiKey(id: number): Promise<PublicApiKeySummary> {
  return requestJson<PublicApiKeySummary>(`/api/v1/admin/public-api-keys/${id}`, {
    method: "DELETE",
  });
}

export async function listLoginEvents(): Promise<LoginEventSummary[]> {
  return requestJson<LoginEventSummary[]>("/api/v1/admin/login-events?limit=20");
}

export async function resolveCandidate(
  candidateId: number,
  input: ResolveCandidateInput,
): Promise<{ status: string }> {
  return requestJson<{ status: string }>(
    `/api/v1/destinations/unmatched/${candidateId}/resolve`,
    {
      method: "POST",
      body: JSON.stringify({
        action: input.action,
        place_id: input.placeId,
        corrected_name: input.correctedName,
        latitude: input.latitude,
        longitude: input.longitude,
        official_address: input.officialAddress,
        road_address: input.roadAddress,
        category: input.category,
        category_code: input.categoryCode,
        review_note: input.reviewNote,
      }),
    },
  );
}

// 검수/보정 카테고리 강제용 8자리 카탈로그(정적이라 캐시 적극 활용).
export async function listCategories(): Promise<CategoryOption[]> {
  return requestJson<CategoryOption[]>("/api/v1/categories");
}

// 외부 검색결과 카테고리 문자열을 카탈로그 8자리 코드로 근사 매핑(LLM 없이). 없으면 null.
export async function matchCategory(
  q: string,
): Promise<{ code: string; label: string } | null> {
  const data = await requestJson<{
    match: { code: string; label: string } | null;
  }>(`/api/v1/categories/match?q=${encodeURIComponent(q)}`);
  return data.match;
}

export async function triggerDeepResearch(
  placeId: number,
): Promise<{ job_id: string; state: string; place_id: number }> {
  return requestJson<{ job_id: string; state: string; place_id: number }>(
    `/api/v1/destinations/${placeId}/deep-research`,
    {
      method: "POST",
      body: JSON.stringify({ max_sources: 8 }),
    },
  );
}

// 반복 수집(source_target) 목록/삭제 + 작업 중지/재시작.
export async function listSourceTargets(): Promise<SourceTargetSummary[]> {
  return requestJson<SourceTargetSummary[]>("/api/v1/source-targets");
}

export async function deleteSourceTarget(
  id: number,
): Promise<{ status: string }> {
  return requestJson<{ status: string }>(`/api/v1/source-targets/${id}`, {
    method: "DELETE",
  });
}

export async function stopRun(jobId: string): Promise<HarvestJob> {
  return requestJson<HarvestJob>(`/api/v1/runs/${jobId}/stop`, {
    method: "POST",
  });
}

export async function restartRun(jobId: string): Promise<HarvestJob> {
  return requestJson<HarvestJob>(`/api/v1/runs/${jobId}/restart`, {
    method: "POST",
  });
}

export type SourceTargetUpdate = {
  scanIntervalMinutes?: number;
  maxRuns?: number;
  isActive?: boolean;
  maxVideos?: number;
  defaultCategoryCode?: string;
};

export async function updateSourceTarget(
  id: number,
  input: SourceTargetUpdate,
): Promise<SourceTargetSummary> {
  return requestJson<SourceTargetSummary>(`/api/v1/source-targets/${id}`, {
    method: "PATCH",
    body: JSON.stringify({
      scan_interval_minutes: input.scanIntervalMinutes,
      max_runs: input.maxRuns,
      is_active: input.isActive,
      max_videos: input.maxVideos,
      default_category_code: input.defaultCategoryCode,
    }),
  });
}

export type CollectedVideo = {
  video_id: string;
  title: string;
  url: string;
  published_at: string | null;
  duration_seconds: number | null;
  channel_title: string | null;
};

export async function getRunVideos(jobId: string): Promise<CollectedVideo[]> {
  return requestJson<CollectedVideo[]>(`/api/v1/runs/${jobId}/videos`);
}

// 작업이 추출한 POI(확정 장소 + 검수 대기 후보). 상태에 따라 결과/검수 뷰로 이동.
export type RunPlace = {
  kind: "place" | "candidate";
  place_id: number | null;
  candidate_id: number | null;
  name: string;
  status: "confirmed" | "needs_review";
  is_domestic: boolean | null;
};

export async function getRunPlaces(jobId: string): Promise<RunPlace[]> {
  return requestJson<RunPlace[]>(`/api/v1/runs/${jobId}/places`);
}

// 단일 작업 요약(작업 상세 페이지용).
export async function getRun(jobId: string): Promise<CrawlRunSummary> {
  return requestJson<CrawlRunSummary>(`/api/v1/runs/${jobId}`);
}

// 작업의 영상별 POI 집계(자동/검수필요/수동완료).
export type RunVideoStat = {
  video_id: string;
  title: string;
  url: string;
  poi_auto: number;
  poi_needs_review: number;
  poi_resolved: number;
  poi_total: number;
};

export async function getRunVideoStats(jobId: string): Promise<RunVideoStat[]> {
  return requestJson<RunVideoStat[]>(`/api/v1/runs/${jobId}/video-stats`);
}

// 영상의 보정 자막(없으면 원본). CandidateTranscript와 동일 형태.
export async function getVideoTranscript(
  videoId: string,
): Promise<CandidateTranscript> {
  return requestJson<CandidateTranscript>(
    `/api/v1/videos/${encodeURIComponent(videoId)}/transcript`,
  );
}

export async function getSourceTargetVideos(
  id: number,
): Promise<CollectedVideo[]> {
  return requestJson<CollectedVideo[]>(`/api/v1/source-targets/${id}/videos`);
}

// 운영 상세 지표(스토리지 + DB 카운트). 백엔드 형태에 느슨하게 맞춘다.
export type MetricsSummary = {
  storage?: {
    enabled?: boolean;
    endpoint?: string;
    console_url?: string;
    retention_policy?: string;
    health?: { ok: boolean; status_code: number | null; error: string | null };
    assets?: { asset_type: string; count: number; size_bytes: number }[];
    total_objects?: number;
    total_size_bytes?: number;
  };
  database?: Record<string, number | Record<string, number>>;
  runs?: Record<string, number>;
};

export async function getMetrics(): Promise<MetricsSummary> {
  return requestJson<MetricsSummary>("/api/v1/metrics");
}

export type PlaceSearchHit = {
  provider: string;
  name: string;
  address: string | null;
  road_address: string | null;
  // 일부 provider 결과는 좌표가 없을 수 있다(역/주차장/플랫폼명 등) → null 허용.
  latitude: number | null;
  longitude: number | null;
  category: string | null;
};

export type PlaceOpinion = {
  best_name?: string;
  latitude?: number;
  longitude?: number;
  category?: string;
  confidence?: number;
  reason?: string;
};

// /place-search는 이제 provider 결과만 즉시 반환한다(빠름). Gemini 의견은 별도 호출.
export type PlaceSearchResult = {
  query: string;
  google: PlaceSearchHit[];
  kakao: PlaceSearchHit[];
  naver: PlaceSearchHit[];
  gemini?: PlaceOpinion | null;
  errors: Record<string, string>;
};

export async function searchPlaces(
  query: string,
  signal?: AbortSignal,
): Promise<PlaceSearchResult> {
  return requestJson<PlaceSearchResult>(
    `/api/v1/place-search?q=${encodeURIComponent(query)}`,
    { signal },
  );
}

export type PlaceOpinionResult = {
  gemini: PlaceOpinion | null;
  error: string | null;
};

// Gemini 의견(느릴 수 있어 provider 결과 표시 후 비동기로 호출).
export async function getPlaceOpinion(
  query: string,
  hits: PlaceSearchHit[],
  signal?: AbortSignal,
): Promise<PlaceOpinionResult> {
  return requestJson<PlaceOpinionResult>("/api/v1/place-search/opinion", {
    method: "POST",
    body: JSON.stringify({ query, hits }),
    signal,
  });
}

// ── 상세 정보 (검수 후보 / 확정 장소) ───────────────────────────────────────
export type CandidateDetail = {
  candidate: {
    id: number;
    ai_place_name: string;
    location_hint: string | null;
    candidate_category: string | null;
    match_status: string;
    confidence_score: number | null;
    speaker_note: string | null;
    source_kind: string | null;
    timestamp_start: string | null;
    timestamp_end: string | null;
    source_text: string | null;
  };
  video: {
    video_id: string;
    title: string | null;
    url: string;
    channel_title: string | null;
    published_at: string | null;
    duration_seconds: number | null;
    description: string | null;
  } | null;
  source_run: {
    id: number;
    run_type: string | null;
    run_type_label: string | null;
    state: string | null;
    model: string | null;
    created_at: string | null;
  } | null;
  provider_evidence: Record<string, unknown> | null;
  sibling_candidates: {
    id: number;
    ai_place_name: string;
    match_status: string;
    candidate_category: string | null;
    place_id: number | null;
  }[];
};

export async function getCandidateDetail(id: number): Promise<CandidateDetail> {
  return requestJson<CandidateDetail>(`/api/v1/destinations/candidates/${id}/detail`);
}

export type CandidateTranscript = {
  text: string | null;
  kind: "corrected" | "raw" | null;
  video_id: string;
};

// 후보의 출처 영상 보정 자막(없으면 원본 자막). 둘 다 없으면 text/kind=null.
export async function getCandidateTranscript(
  id: number,
): Promise<CandidateTranscript> {
  return requestJson<CandidateTranscript>(
    `/api/v1/destinations/candidates/${id}/transcript`,
  );
}

export async function deleteCandidate(
  id: number,
): Promise<{ deleted: boolean; id: number }> {
  return requestJson(`/api/v1/destinations/candidates/${id}`, {
    method: "DELETE",
  });
}

export type PlaceMention = {
  timestamp_start: string | null;
  timestamp_end?: string | null;
  source_kind: string | null;
  source_text: string | null;
  speaker_note?: string | null;
};
export type PlaceDetailVideo = {
  video_id: string;
  title: string | null;
  url: string;
  channel_title: string | null;
  published_at: string | null;
  mention_count: number;
  mentions: PlaceMention[];
};
export type PlaceDetail = {
  place: {
    place_id: number;
    name: string;
    category: string | null;
    category_code_suggestion: string | null;
    sigungu_code: string | null;
    sigungu_name: string | null;
    legal_dong_code: string | null;
    legal_dong_name: string | null;
    official_address: string | null;
    road_address: string | null;
    latitude: number | null;
    longitude: number | null;
    is_geocoded: boolean;
    description: string | null;
    gemini_enriched_description: string | null;
    detailed_research_content: string | null;
  };
  stats: { mention_count: number; video_count: number; channel_count: number };
  source_videos: PlaceDetailVideo[];
};

export async function getPlaceDetail(placeId: number): Promise<PlaceDetail> {
  return requestJson<PlaceDetail>(`/api/v1/destinations/${placeId}/detail`);
}

export async function deletePlace(placeId: number): Promise<{
  deleted: boolean;
  place_id: number;
  reverted_candidates: number;
}> {
  return requestJson(`/api/v1/destinations/${placeId}`, {
    method: "DELETE",
  });
}

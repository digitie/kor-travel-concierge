// 백엔드 API 베이스 URL. `.env`의 NEXT_PUBLIC_API_BASE_URL로 주입한다.
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

// 비로컬 백엔드 인증용 API 키. 비어 있으면 헤더를 붙이지 않는다(로컬/E2E 무인증).
export const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

// VWorld 지도 서비스 키 (브라우저 직접 로드).
export const VWORLD_SERVICE_KEY =
  process.env.NEXT_PUBLIC_VWORLD_SERVICE_KEY ?? "";

export type HarvestTargetType = "keyword" | "channel" | "playlist";
export type DestinationSort = "latest" | "mention_count" | "name" | "category";
export type DestinationExportFormat = "xlsx" | "gpx" | "kml";

export type StartHarvestInput = {
  targetType: HarvestTargetType;
  targetValue: string;
  maxVideos: number;
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
  match_status: string;
  timestamp_start: string | null;
};

export type CrawlRunSummary = {
  job_id: string;
  job_type: string;
  source: string;
  target_type: string | null;
  target_id: string | null;
  state: string;
  progress: number;
  current_message: string | null;
  status_logs: RunStatusLog[];
  retry_count: number;
  last_error: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

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
  gemini_engine_version: string;
  gemini_engine_default: string;
  gemini_engine_options: string[];
};

export type RuntimeSettingsUpdate = {
  gemini_engine_version: string;
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
  reviewNote?: string;
};

function harvestPayload(input: StartHarvestInput) {
  return {
    query: input.targetType === "keyword" ? input.targetValue : undefined,
    channel_id: input.targetType === "channel" ? input.targetValue : undefined,
    playlist_id: input.targetType === "playlist" ? input.targetValue : undefined,
    max_videos: input.maxVideos,
  };
}

// 백엔드 요청 공통 헤더. API_KEY가 설정된 경우에만 X-API-Key를 주입한다.
function buildHeaders(extra: HeadersInit = {}): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
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

export async function getHarvestStatus(jobId: string): Promise<HarvestStatus> {
  return requestJson<HarvestStatus>(`/api/v1/harvest/${jobId}`);
}

export async function listDestinations(
  sort: DestinationSort = "latest",
): Promise<DestinationSummary[]> {
  return requestJson<DestinationSummary[]>(`/api/v1/destinations?sort=${sort}`);
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

export async function listUnmatchedCandidates(): Promise<UnmatchedCandidate[]> {
  return requestJson<UnmatchedCandidate[]>("/api/v1/destinations/unmatched");
}

export async function listRuns({
  state,
  limit = 12,
}: {
  state?: "pending" | "running" | "done" | "failed" | string;
  limit?: number;
} = {}): Promise<CrawlRunSummary[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (state) {
    params.set("state", state);
  }
  return requestJson<CrawlRunSummary[]>(`/api/v1/runs?${params.toString()}`);
}

export async function listRunQueue(): Promise<CrawlRunSummary[]> {
  const [running, pending] = await Promise.all([
    listRuns({ state: "running", limit: 50 }),
    listRuns({ state: "pending", limit: 50 }),
  ]);
  return [
    ...running.sort(compareRunIdAsc),
    ...pending.sort(compareRunIdAsc),
  ];
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
        review_note: input.reviewNote,
      }),
    },
  );
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

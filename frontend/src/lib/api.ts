// 백엔드 API 베이스 URL. `.env`의 NEXT_PUBLIC_API_BASE_URL로 주입한다.
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

// VWorld 지도 서비스 키 (브라우저 직접 로드).
export const VWORLD_SERVICE_KEY =
  process.env.NEXT_PUBLIC_VWORLD_SERVICE_KEY ?? "";

export type HarvestTargetType = "keyword" | "channel" | "playlist";

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
  last_error: string | null;
  result: Record<string, unknown> | null;
};

export type DestinationSummary = {
  place_id: number;
  name: string;
  latitude: number;
  longitude: number;
  category: string | null;
  official_address: string | null;
  is_geocoded: boolean;
};

function harvestPayload(input: StartHarvestInput) {
  return {
    query: input.targetType === "keyword" ? input.targetValue : undefined,
    channel_id: input.targetType === "channel" ? input.targetValue : undefined,
    playlist_id: input.targetType === "playlist" ? input.targetValue : undefined,
    max_videos: input.maxVideos,
  };
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `API 요청 실패: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function startHarvest(input: StartHarvestInput): Promise<HarvestJob> {
  return requestJson<HarvestJob>("/api/harvest", {
    method: "POST",
    body: JSON.stringify(harvestPayload(input)),
  });
}

export async function getHarvestStatus(jobId: string): Promise<HarvestStatus> {
  return requestJson<HarvestStatus>(`/api/harvest/${jobId}`);
}

export async function listDestinations(): Promise<DestinationSummary[]> {
  return requestJson<DestinationSummary[]>("/api/destinations");
}

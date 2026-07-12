import {
  type PlaceSearchHit,
  type ResolveCandidateInput,
  type SelectedPlaceHitEvidence,
} from "./api";

export type SelectedPlaceHit = {
  candidateId: number;
  hit: PlaceSearchHit;
  query: string;
  searchedAt: string;
  selectedAt: string;
};

export type ReviewResolutionForm = {
  name: string;
  latitude: string;
  longitude: string;
  category: string;
  categoryCode: string;
};

export type NearbyPlaceCandidate = {
  placeId: number;
  name: string;
  officialAddress: string | null;
  roadAddress: string | null;
  latitude: number;
  longitude: number;
  apiSource: string | null;
  distanceMeters: number;
  nameCompatible: boolean | null;
  providerIdMatch: boolean | null;
};

export function isPlaceHitStorageAllowed(hit: PlaceSearchHit): boolean {
  return hit.storage_allowed === true && hit.provider !== "google";
}

export function placeHitStorageBlockReason(hit: PlaceSearchHit): string | null {
  if (hit.provider === "google") {
    return hit.storage_block_reason ?? "정책 결정 전에는 Google 결과를 저장할 수 없습니다.";
  }
  return hit.storage_allowed ? null : hit.storage_block_reason ?? "저장이 허용되지 않은 결과입니다.";
}

export function selectedHitEvidence(
  selected: SelectedPlaceHit,
): SelectedPlaceHitEvidence {
  return {
    provider: selected.hit.provider,
    native_id: selected.hit.native_id,
    query: selected.query,
    searched_at: selected.searchedAt,
    selected_at: selected.selectedAt,
    name: selected.hit.name,
    address: selected.hit.address,
    road_address: selected.hit.road_address,
    latitude: selected.hit.latitude,
    longitude: selected.hit.longitude,
    category: selected.hit.category,
  };
}

export function buildCreatePlaceResolution(
  form: ReviewResolutionForm,
  selected: SelectedPlaceHit | null,
  duplicate?: {
    resolution: "merge_existing" | "create_new";
    placeId?: number;
  },
): ResolveCandidateInput {
  return {
    action: "create_place",
    correctedName: form.name,
    latitude: Number(form.latitude),
    longitude: Number(form.longitude),
    officialAddress: selected?.hit.address ?? undefined,
    roadAddress: selected?.hit.road_address ?? undefined,
    category: form.category || undefined,
    categoryCode: form.categoryCode || undefined,
    apiSource: selected?.hit.provider ?? "manual",
    selectedHit: selected ? selectedHitEvidence(selected) : undefined,
    duplicateResolution: duplicate?.resolution,
    duplicatePlaceId: duplicate?.placeId,
  };
}

export function isSelectedHitModified(
  form: ReviewResolutionForm,
  selected: SelectedPlaceHit,
): boolean {
  return (
    form.name.trim() !== selected.hit.name.trim() ||
    Number(form.latitude) !== selected.hit.latitude ||
    Number(form.longitude) !== selected.hit.longitude ||
    (form.category.trim() || null) !== selected.hit.category
  );
}

export function parseNearbyPlaceConflict(
  error: unknown,
): NearbyPlaceCandidate[] | null {
  const errorObject = asRecord(error);
  if (asNumber(errorObject?.status) !== 409) return null;
  const body = asRecord(errorObject?.body);
  const detail = asRecord(body?.detail);
  if (detail?.code !== "nearby_place_confirmation_required") return null;
  if (!Array.isArray(detail.nearby_places)) return null;

  const places = detail.nearby_places
    .map((value) => normalizeNearbyPlace(value))
    .filter((value): value is NearbyPlaceCandidate => value !== null);
  return places.length > 0 ? places : null;
}

function normalizeNearbyPlace(value: unknown): NearbyPlaceCandidate | null {
  const item = asRecord(value);
  const placeId = asNumber(item?.place_id);
  const name = typeof item?.name === "string" ? item.name : null;
  const distanceMeters = asNumber(item?.distance_m ?? item?.distance_meters);
  const latitude = asNumber(item?.latitude);
  const longitude = asNumber(item?.longitude);
  if (
    placeId == null ||
    name == null ||
    distanceMeters == null ||
    latitude == null ||
    longitude == null
  ) {
    return null;
  }
  return {
    placeId,
    name,
    officialAddress: asNullableString(item?.official_address),
    roadAddress: asNullableString(item?.road_address),
    latitude,
    longitude,
    apiSource: asNullableString(item?.api_source),
    distanceMeters,
    nameCompatible: asNullableBoolean(item?.name_compatible),
    providerIdMatch: asNullableBoolean(item?.provider_id_match),
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asNullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asNullableBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

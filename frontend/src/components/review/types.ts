import type { PlaceSearchProvider } from "@/lib/api";
import type { NearbyPlaceCandidate } from "@/lib/review-provenance";

export const PLACE_SEARCH_PROVIDER_LABELS: Record<
  PlaceSearchProvider,
  string
> = {
  google: "Google Places",
  kakao: "Kakao",
  naver: "Naver",
};

export const PLACE_SEARCH_PROVIDER_ORDER = [
  "google",
  "kakao",
  "naver",
] as const satisfies readonly PlaceSearchProvider[];

export type ConfirmFormNearbyConflict = {
  placeName: string;
  places: readonly NearbyPlaceCandidate[];
};

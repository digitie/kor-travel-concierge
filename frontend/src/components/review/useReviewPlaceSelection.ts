"use client";

import { selectableSearchHits } from "@/components/review/searchHitNumber";
import type {
  DestinationSummary,
  PlaceOpinion,
  PlaceSearchHit,
  PlaceSearchResult,
  UnmatchedCandidate,
} from "@/lib/api";
import { matchCategory } from "@/lib/api";
import {
  isPlaceHitSelectable,
  type SelectedPlaceHit,
} from "@/lib/review-provenance";
import { useMemo, type SetStateAction } from "react";
import { type ReviewFormState } from "./review-ui-store";

import type { NearbyConflict } from "./review-workspace-model";
import { hitPlace } from "./review-workspace-model";

export function useReviewPlaceSelection({
  selected,
  cancelCategoryMatch,
  result,
  activeQuery,
  setSelectedHit,
  setNearbyConflict,
  setFormCandidateId,
  setForm,
  categoryEdited,
  categoryMatchAbortRef,
  categoryMatchRequestRef,
  selectedCandidateIdRef,
}: {
  selected: UnmatchedCandidate | null;
  cancelCategoryMatch: () => void;
  result: PlaceSearchResult | null;
  activeQuery: string;
  setSelectedHit: (action: SetStateAction<SelectedPlaceHit | null>) => void;
  setNearbyConflict: (action: SetStateAction<NearbyConflict | null>) => void;
  setFormCandidateId: (action: SetStateAction<number | null>) => void;
  setForm: (action: SetStateAction<ReviewFormState>) => void;
  categoryEdited: boolean;
  categoryMatchAbortRef: React.RefObject<AbortController | null>;
  categoryMatchRequestRef: React.RefObject<number>;
  selectedCandidateIdRef: React.RefObject<number | null>;
}) {
  function selectHit(hit: PlaceSearchHit) {
    if (!selected || !isPlaceHitSelectable(hit)) return;
    cancelCategoryMatch();
    const candidateId = selected.id;
    const nextSelectedHit: SelectedPlaceHit = {
      candidateId,
      hit,
      query: result?.query ?? activeQuery,
      searchedAt: result?.searched_at ?? new Date().toISOString(),
      selectedAt: new Date().toISOString(),
    };
    setSelectedHit(nextSelectedHit);
    setNearbyConflict(null);
    setFormCandidateId(candidateId);
    setForm((prev) => ({
      ...prev,
      name: hit.name,
      latitude: hit.latitude == null ? "" : String(hit.latitude),
      longitude: hit.longitude == null ? "" : String(hit.longitude),
    }));
    // 검색결과 카테고리 매칭이 되면 그 값을 쓰고, 실패하면 후보의 기본 카테고리를 유지한다.
    // 사용자가 드롭다운을 직접 바꾼 뒤에는 자동 매칭으로 덮어쓰지 않는다.
    if (hit.category && !categoryEdited) {
      const controller = new AbortController();
      categoryMatchAbortRef.current = controller;
      const requestId = ++categoryMatchRequestRef.current;
      void matchCategory(hit.category, controller.signal)
        .then((match) => {
          if (
            !match ||
            controller.signal.aborted ||
            requestId !== categoryMatchRequestRef.current ||
            candidateId !== selectedCandidateIdRef.current
          ) {
            return;
          }
          setForm((prev) => ({
            ...prev,
            categoryCode: match.code,
            category: match.label,
          }));
        })
        // 카테고리 자동 매핑 실패는 후보 선택 자체를 막지 않는다.
        .catch(() => {})
        .finally(() => {
          if (requestId === categoryMatchRequestRef.current) {
            categoryMatchAbortRef.current = null;
          }
        });
    }
  }
  function applyGemini(gemini: PlaceOpinion) {
    // Gemini 의견도 카테고리는 덮어쓰지 않는다(드롭다운이 단일 출처).
    cancelCategoryMatch();
    setSelectedHit(null);
    setNearbyConflict(null);
    setFormCandidateId(selected?.id ?? null);
    setForm((prev) => ({
      ...prev,
      name: gemini.best_name ?? prev.name,
      latitude:
        gemini.latitude != null ? String(gemini.latitude) : prev.latitude,
      longitude:
        gemini.longitude != null ? String(gemini.longitude) : prev.longitude,
    }));
  }
  return { selectHit, applyGemini };
}

export function useReviewMapPlaces({
  allHits,
  externalResolutionEnabled,
  form,
  activeSelectedHit,
}: {
  allHits: PlaceSearchHit[];
  externalResolutionEnabled: boolean;
  form: ReviewFormState;
  activeSelectedHit: SelectedPlaceHit | null;
}) {
  const selectableHits = useMemo(
    () => selectableSearchHits(allHits),
    [allHits],
  );
  const mapHitEntries = useMemo(
    () => selectableHits.map((hit, index) => ({ placeId: index + 1, hit })),
    [selectableHits],
  );
  const mapPlaces = useMemo<DestinationSummary[]>(() => {
    if (!externalResolutionEnabled) return [];
    const hits = mapHitEntries.map(({ hit, placeId }) =>
      hitPlace(hit, placeId),
    );
    const lat = Number(form.latitude);
    const lng = Number(form.longitude);
    if (Number.isFinite(lat) && Number.isFinite(lng) && form.latitude) {
      hits.unshift({
        place_id: 9999,
        name: form.name || "선택 위치",
        description: null,
        gemini_enriched_description: null,
        latitude: lat,
        longitude: lng,
        category: form.category || null,
        official_address: activeSelectedHit?.hit.address ?? null,
        road_address: activeSelectedHit?.hit.road_address ?? null,
        is_geocoded: true,
        mention_count: 0,
        source_channel_count: 0,
        source_videos: [],
      });
    }
    return hits;
  }, [activeSelectedHit, externalResolutionEnabled, form, mapHitEntries]);
  return { selectableHits, mapHitEntries, mapPlaces };
}

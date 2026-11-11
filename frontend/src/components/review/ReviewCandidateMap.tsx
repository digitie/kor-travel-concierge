"use client";

import { reviewCandidateMapProps } from "./review-view-props";

import { VWorldMap } from "@/components/VWorldMap";

export function ReviewCandidateMap({
  externalResolutionEnabled,
  mapPlaces,
  form,
  mapHitEntries,
  selectHit,
}: ReturnType<typeof reviewCandidateMapProps>) {
  return (
    <section className="min-h-[28rem] overflow-hidden border-t lg:min-h-0 lg:border-t-0 lg:border-l">
      {externalResolutionEnabled ? (
        <VWorldMap
          places={mapPlaces}
          selectedPlaceId={form.latitude ? 9999 : null}
          onSelectPlace={(placeId) => {
            const entry = mapHitEntries.find(
              (item) => item.placeId === placeId,
            );
            if (entry) selectHit(entry.hit);
          }}
        />
      ) : (
        <div className="flex h-full min-h-[28rem] items-center justify-center bg-muted/20 p-6 text-center text-sm text-muted-foreground">
          복구 전용 화면에서는 외부 지도와 장소 검색을 호출하지 않습니다.
        </div>
      )}
    </section>
  );
}

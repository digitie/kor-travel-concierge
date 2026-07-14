"use client";

import type { Ref } from "react";
import { Loader2Icon, SparklesIcon } from "lucide-react";

import type {
  PlaceOpinion,
  PlaceSearchHit,
  PlaceSearchResult,
} from "@/lib/api";
import { placeHitStorageBlockReason } from "@/lib/review-provenance";
import { searchHitShortcutNumber } from "@/components/review/searchHitNumber";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  PLACE_SEARCH_PROVIDER_LABELS,
  PLACE_SEARCH_PROVIDER_ORDER,
} from "@/components/review/types";

export type SearchResultsPanelProps = {
  resultsRef?: Ref<HTMLDivElement>;
  activeQuery: string;
  result: PlaceSearchResult | null | undefined;
  loading: boolean;
  selectableHitCount: number;
  /**
   * 렌더 순서와 동일한 평탄 hit 목록(`allHits`). 각 행의 1–9 서수 배지와 키보드
   * 단축키 선택이 이 배열 순서(reference)를 단일 출처로 쓴다(T-187).
   */
  orderedHits?: readonly PlaceSearchHit[];
  selectedHit: PlaceSearchHit | null;
  opinionRequested: boolean;
  opinion: PlaceOpinion | null;
  opinionLoading: boolean;
  opinionError: string | null | undefined;
  onRequestOpinion: () => void;
  onRetryOpinion: () => void;
  onApplyOpinion: (opinion: PlaceOpinion) => void;
  onSelectHit: (hit: PlaceSearchHit) => void;
};

export function SearchResultsPanel({
  resultsRef,
  activeQuery,
  result,
  loading,
  selectableHitCount,
  orderedHits,
  selectedHit,
  opinionRequested,
  opinion,
  opinionLoading,
  opinionError,
  onRequestOpinion,
  onRetryOpinion,
  onApplyOpinion,
  onSelectHit,
}: SearchResultsPanelProps) {
  return (
    <div ref={resultsRef} className="scroll-mt-3 flex flex-col gap-3">
      {!opinionRequested ? (
        <Button
          type="button"
          variant="outline"
          className="w-full"
          disabled={selectableHitCount === 0}
          onClick={onRequestOpinion}
        >
          <SparklesIcon data-icon="inline-start" />
          AI(Gemini) 의견 요청
        </Button>
      ) : opinion ? (
        <GeminiCard
          gemini={opinion}
          onApply={() => onApplyOpinion(opinion)}
        />
      ) : opinionLoading ? (
        <div className="flex items-center gap-2 rounded-xl border border-primary/40 bg-primary/5 p-3 text-sm text-muted-foreground">
          <Loader2Icon className="size-4 animate-spin text-primary" />
          Gemini 의견 분석 중…
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="flex items-center gap-1.5 rounded-xl border p-3 text-xs text-muted-foreground">
            <SparklesIcon className="size-3.5 shrink-0" />
            {opinionError ?? "Gemini 의견이 없습니다."}
          </p>
          <Button
            type="button"
            size="xs"
            variant="ghost"
            onClick={onRetryOpinion}
          >
            다시 요청
          </Button>
        </div>
      )}
      {PLACE_SEARCH_PROVIDER_ORDER.map((provider) => (
        <ProviderSection
          key={provider}
          label={PLACE_SEARCH_PROVIDER_LABELS[provider]}
          hits={result?.[provider] ?? []}
          error={result?.errors?.[provider]}
          loading={loading}
          orderedHits={orderedHits}
          selectedHit={selectedHit}
          onSelect={onSelectHit}
        />
      ))}
      {!activeQuery ? (
        <p className="text-xs text-muted-foreground">
          후보를 선택하면 자동 검색합니다. 직접 검색어를 입력할 수도 있습니다.
        </p>
      ) : null}
    </div>
  );
}

function GeminiCard({
  gemini,
  onApply,
}: {
  gemini: PlaceOpinion;
  onApply: () => void;
}) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-primary/40 bg-primary/5 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          <SparklesIcon className="size-4 text-primary" />
          Gemini 의견
        </p>
        {gemini.confidence != null ? (
          <Badge variant="outline">
            신뢰도 {Math.round(gemini.confidence * 100)}%
          </Badge>
        ) : null}
      </div>
      <p className="text-sm font-medium">{gemini.best_name ?? "-"}</p>
      {gemini.reason ? (
        <p className="text-xs text-muted-foreground">{gemini.reason}</p>
      ) : null}
      {gemini.latitude != null && gemini.longitude != null ? (
        <Button type="button" size="xs" variant="outline" onClick={onApply}>
          이 결과 사용
        </Button>
      ) : null}
    </div>
  );
}

function ProviderSection({
  label,
  hits,
  error,
  loading,
  orderedHits,
  selectedHit,
  onSelect,
}: {
  label: string;
  hits: readonly PlaceSearchHit[];
  error?: string;
  loading: boolean;
  orderedHits?: readonly PlaceSearchHit[];
  selectedHit: PlaceSearchHit | null;
  onSelect: (hit: PlaceSearchHit) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold">{label}</p>
        <Badge variant="outline">{hits.length}</Badge>
      </div>
      {error ? (
        <p className="text-xs text-destructive">{error}</p>
      ) : hits.length === 0 ? (
        <p className="rounded-lg border p-2 text-xs text-muted-foreground">
          {loading ? "검색 중…" : "결과 없음"}
        </p>
      ) : (
        hits.map((hit, index) => {
          const hasCoords = hit.latitude != null && hit.longitude != null;
          const storageBlockReason = placeHitStorageBlockReason(hit);
          const selectable = hasCoords && storageBlockReason == null;
          const isSelected = selectedHit === hit;
          // 서수는 선택 가능 hit(orderedHits, 좌표+저장 허용) reference 순서를 단일
          // 출처로 쓴다. 키보드 1–9·지도 번호와 동일 순서/번호이며, 선택 불가 행에는
          // 배지·단축키를 붙이지 않는다(로딩 중 재정렬로도 어긋나지 않음).
          const shortcutNumber = searchHitShortcutNumber(
            orderedHits,
            hit,
            selectable,
          );
          return (
            <button
              key={`${hit.provider}-${hit.native_id ?? index}`}
              type="button"
              disabled={!selectable}
              aria-pressed={isSelected}
              aria-keyshortcuts={shortcutNumber ? String(shortcutNumber) : undefined}
              title={storageBlockReason ?? undefined}
              onClick={() => onSelect(hit)}
              className="flex flex-col gap-0.5 rounded-lg border p-2 text-left text-xs transition-colors hover:border-primary hover:bg-muted aria-pressed:border-primary aria-pressed:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-1.5">
                  {shortcutNumber ? (
                    <Badge
                      variant="secondary"
                      className="shrink-0 px-1.5 font-mono tabular-nums"
                    >
                      {shortcutNumber}
                    </Badge>
                  ) : null}
                  <span className="truncate font-medium">{hit.name}</span>
                </span>
                {hit.category ? (
                  <span className="shrink-0 text-muted-foreground">
                    {hit.category}
                  </span>
                ) : null}
              </span>
              <span className="truncate text-muted-foreground">
                {hit.road_address ?? hit.address ?? "-"}
              </span>
              <span className="text-muted-foreground">
                {hasCoords
                  ? `${hit.latitude!.toFixed(5)}, ${hit.longitude!.toFixed(5)}`
                  : "좌표 없음(선택 불가)"}
              </span>
              {storageBlockReason ? (
                <span className="text-warning">{storageBlockReason}</span>
              ) : null}
            </button>
          );
        })
      )}
    </div>
  );
}

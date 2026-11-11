"use client";

import { reviewCandidateSummaryProps } from "./review-view-props";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  candidateReviewStateLabel,
  categoryDisplayLabel,
} from "@/lib/display-labels";
import { youtubeWatchUrl } from "@/lib/format";
import { ExternalLinkIcon, InfoIcon } from "lucide-react";

export function ReviewCandidateSummary({
  selected,
  openDetail,
}: ReturnType<typeof reviewCandidateSummaryProps>) {
  if (!selected) return null;
  return (
    <div className="flex flex-col gap-2 rounded-control border border-border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">{selected.ai_place_name}</span>
        <Badge variant="outline">
          {categoryDisplayLabel(selected.candidate_category)}
        </Badge>
        <Badge variant="secondary">
          {candidateReviewStateLabel(selected.review_state)}
        </Badge>
      </div>
      {selected.location_hint ? (
        <p className="text-xs text-muted-foreground">
          위치 힌트: {selected.location_hint}
        </p>
      ) : null}
      {selected.video_is_excluded &&
      selected.review_state === "needs_review" ? (
        <p
          role="status"
          className="rounded-control border border-warning bg-warning-tint p-2 text-xs text-warning"
        >
          출처 영상은 제외 상태입니다. 후보를 복구하거나 다시 확정해도 영상
          제외는 유지됩니다.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <a
          href={youtubeWatchUrl(selected.video_id, selected.timestamp_start)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex w-fit items-center gap-1 text-xs text-primary hover:underline"
        >
          영상 보기 <ExternalLinkIcon className="size-3" />
        </a>
        <Button
          type="button"
          size="xs"
          variant="outline"
          onClick={() => openDetail(selected.id)}
        >
          <InfoIcon data-icon="inline-start" />
          상세 보기
        </Button>
      </div>
    </div>
  );
}

"use client";

import {
  reviewCandidateEditorProps,
  reviewDeepLinkNoticeProps,
  reviewEmptySelectionProps,
  reviewCandidateActionsProps,
  reviewCandidateSummaryProps,
  reviewEmptySelectionStatus
} from "./review-view-props";

import { Button } from "@/components/ui/button";
import { candidateReviewStateLabel } from "@/lib/display-labels";
import { DEFAULT_REVIEW_LIST_STATE } from "@/lib/review-list-state";

import { ReviewCandidateActions } from "./ReviewCandidateActions";
import { ReviewCandidateSummary } from "./ReviewCandidateSummary";

export function ReviewCandidateEditor(
  model: ReturnType<typeof reviewCandidateEditorProps>,
) {
  const { selected, deepLinkedCandidateId, deepLinkDetailQuery } = model;
  return (
    <section className="flex min-h-0 flex-col gap-5 overflow-y-auto p-4 lg:p-6">
      {selected ? (
        <>
          {deepLinkedCandidateId != null &&
          deepLinkDetailQuery.data != null &&
          deepLinkDetailQuery.isError ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-destructive bg-destructive-tint p-3 text-sm text-destructive">
              <span role="alert">
                최신 후보 상세를 다시 확인하지 못해 이전 정보를 표시합니다.
              </span>
              <Button
                type="button"
                size="xs"
                variant="outline"
                disabled={deepLinkDetailQuery.isFetching}
                onClick={() => void deepLinkDetailQuery.refetch()}
              >
                상세 다시 확인
              </Button>
            </div>
          ) : null}
          <ReviewDeepLinkNotice {...reviewDeepLinkNoticeProps(model)} />
          <ReviewCandidateSummary {...reviewCandidateSummaryProps(model)} />

          <ReviewCandidateActions {...reviewCandidateActionsProps(model)} />
        </>
      ) : (
        <ReviewEmptySelection {...reviewEmptySelectionProps(model)} />
      )}
    </section>
  );
}

function ReviewEmptySelection({
  candidateAdvancePending,
  candidateInitialLoading,
  candidateLoadError,
  queueCompleted,
  candidateAdvanceError,
  isRemovedView,
  retryCandidateLoad,
  deepLinkedCandidateId,
  restartCandidateSnapshot,
  retryCandidateAdvance,
}: ReturnType<typeof reviewEmptySelectionProps>) {
  const { role, message } = reviewEmptySelectionStatus({
    candidateAdvancePending,
    candidateInitialLoading,
    candidateLoadError,
    queueCompleted,
    candidateAdvanceError,
    isRemovedView,
  });

  return (
    <div className="flex flex-col gap-2 text-sm text-muted-foreground">
      <p role={role} aria-live={candidateInitialLoading ? "polite" : undefined}>
        {message}
      </p>
      {!candidateInitialLoading && candidateLoadError ? (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={retryCandidateLoad}
          >
            검수 후보 다시 불러오기
          </Button>
          {deepLinkedCandidateId != null ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => void restartCandidateSnapshot()}
            >
              현재 목록으로
            </Button>
          ) : null}
        </div>
      ) : candidateAdvanceError ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={retryCandidateAdvance}
        >
          다음 후보 다시 불러오기
        </Button>
      ) : null}
    </div>
  );
}

function ReviewDeepLinkNotice({
  deepLinkStatusOut,
  selected,
  restartCandidateSnapshot,
  deepLinkFilterOut,
  updateReviewListState,
  reviewSort,
  reviewStatus,
  deepLinkLoadedOut,
}: ReturnType<typeof reviewDeepLinkNoticeProps>) {
  if (!selected) return null;

  if (deepLinkStatusOut) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-warning bg-warning-tint p-3 text-sm">
        <span role="status">
          이 후보는 현재 {candidateReviewStateLabel(selected.review_state)}{" "}
          상태라 검수 저장·제외·삭제를 할 수 없습니다.
        </span>
        <Button
          type="button"
          size="xs"
          variant="outline"
          onClick={() => void restartCandidateSnapshot()}
        >
          현재 목록으로
        </Button>
      </div>
    );
  }
  if (deepLinkFilterOut) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-brand bg-brand-tint p-3 text-sm">
        <span role="status">현재 필터 밖 후보를 단건 상세로 열었습니다.</span>
        <Button
          type="button"
          size="xs"
          variant="outline"
          onClick={() =>
            updateReviewListState({
              ...DEFAULT_REVIEW_LIST_STATE,
              sort: reviewSort,
              status: reviewStatus,
            })
          }
        >
          필터 해제
        </Button>
      </div>
    );
  }
  if (deepLinkLoadedOut) {
    return (
      <p
        role="status"
        className="rounded-control border border-brand bg-brand-tint p-3 text-sm"
      >
        현재 필터에는 포함되지만 아직 불러온 페이지 밖 후보입니다. 목록 전체를
        순회하지 않고 단건 상세로 바로 열었습니다.
      </p>
    );
  }
  return null;
}

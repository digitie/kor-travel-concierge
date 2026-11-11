"use client";

import {
  reviewQueueContentsProps,
  reviewQueueRowsProps,
} from "./review-view-props";

import { CandidateTable } from "@/components/review/CandidateTable";
import { Button } from "@/components/ui/button";
import { isReviewCandidateActionable } from "@/lib/review-list-state";
import { Loader2Icon } from "lucide-react";

import { type ReviewWorkspaceModel } from "./review-view-props";

export function ReviewQueueRows(
  model: ReturnType<typeof reviewQueueRowsProps>,
) {
  const { canLoadMoreCandidates, candidatesQuery } = model;
  return (
    <div className="min-h-0 lg:flex-1 lg:overflow-y-auto">
      <ReviewQueueContents {...reviewQueueContentsProps(model)} />
      {canLoadMoreCandidates ? (
        <div className="border-t bg-background p-2 lg:sticky lg:bottom-0">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="w-full"
            disabled={candidatesQuery.isFetchingNextPage}
            onClick={() => {
              if (
                !candidatesQuery.hasNextPage ||
                candidatesQuery.isFetchingNextPage
              ) {
                return;
              }
              void candidatesQuery.fetchNextPage({
                cancelRefetch: false,
              });
            }}
          >
            {candidatesQuery.isFetchingNextPage ? (
              <Loader2Icon data-icon="inline-start" className="animate-spin" />
            ) : null}
            후보 더 불러오기
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ReviewQueueContents({
  candidates,
  candidateAdvancePending,
  candidateAdvanceError,
  retryCandidateAdvance,
  candidateInitialLoading,
  candidateLoadError,
  retryCandidateLoad,
  deepLinkedCandidateId,
  restartCandidateSnapshot,
  queueCompleted,
  isRemovedView,
  selected,
  selectedCandidateSet,
  cartSet,
  bulkSelectableLoadedCandidateIds,
  allLoadedCandidatesSelected,
  someLoadedCandidatesSelected,
  bulkSelectionLimitReached,
  candidateActionPending,
  deepLinkItem,
  toggleAllLoadedCandidates,
  toggleCandidateSelection,
  pickCandidate,
  toggleCart,
  openDetail,
  requestCandidateDelete,
  restoreCandidateFromRemovedList,
}: ReturnType<typeof reviewQueueContentsProps>) {
  if (candidates.length === 0)
    return (
      <ReviewEmptyQueue
        candidateAdvancePending={candidateAdvancePending}
        candidateAdvanceError={candidateAdvanceError}
        retryCandidateAdvance={retryCandidateAdvance}
        candidateInitialLoading={candidateInitialLoading}
        candidateLoadError={candidateLoadError}
        retryCandidateLoad={retryCandidateLoad}
        deepLinkedCandidateId={deepLinkedCandidateId}
        restartCandidateSnapshot={restartCandidateSnapshot}
        queueCompleted={queueCompleted}
        isRemovedView={isRemovedView}
      />
    );
  return (
    <CandidateTable
      candidates={candidates}
      currentCandidateId={selected?.id ?? null}
      selectedCandidateIds={selectedCandidateSet}
      cartVideoIds={cartSet}
      bulkSelectableCandidateIds={bulkSelectableLoadedCandidateIds}
      allLoadedCandidatesSelected={allLoadedCandidatesSelected}
      someLoadedCandidatesSelected={someLoadedCandidatesSelected}
      bulkSelectionLimitReached={bulkSelectionLimitReached}
      candidateActionPending={candidateActionPending}
      removedMode={isRemovedView}
      isCandidateActionable={(candidate) =>
        isReviewCandidateActionable(
          deepLinkItem?.id === candidate.id ? deepLinkItem : candidate,
        )
      }
      onToggleAllLoadedCandidates={toggleAllLoadedCandidates}
      onToggleSelect={toggleCandidateSelection}
      onPick={pickCandidate}
      onToggleCart={toggleCart}
      onOpenDetail={openDetail}
      onRequestDelete={requestCandidateDelete}
      onRestore={restoreCandidateFromRemovedList}
    />
  );
}

function ReviewEmptyQueue({
  candidateAdvancePending,
  candidateAdvanceError,
  retryCandidateAdvance,
  candidateInitialLoading,
  candidateLoadError,
  retryCandidateLoad,
  deepLinkedCandidateId,
  restartCandidateSnapshot,
  queueCompleted,
  isRemovedView,
}: Pick<
  ReviewWorkspaceModel,
  | "candidateAdvancePending"
  | "candidateAdvanceError"
  | "retryCandidateAdvance"
  | "candidateInitialLoading"
  | "candidateLoadError"
  | "retryCandidateLoad"
  | "deepLinkedCandidateId"
  | "restartCandidateSnapshot"
  | "queueCompleted"
  | "isRemovedView"
>) {
  if (candidateAdvancePending) {
    return (
      <div className="flex flex-col gap-2 rounded-lg border p-3 text-xs text-muted-foreground">
        <p role="status">
          {candidateAdvanceError
            ? candidateAdvanceError
            : "다음 검수 후보를 불러오는 중…"}
        </p>
        {candidateAdvanceError ? (
          <Button
            type="button"
            size="xs"
            variant="outline"
            onClick={retryCandidateAdvance}
          >
            다시 시도
          </Button>
        ) : null}
      </div>
    );
  }
  if (candidateInitialLoading) {
    return (
      <p
        role="status"
        aria-live="polite"
        className="rounded-lg border p-3 text-xs text-muted-foreground"
      >
        검수 후보를 불러오는 중…
      </p>
    );
  }
  if (candidateLoadError) {
    return (
      <div className="flex flex-col gap-2 rounded-control border border-destructive p-3 text-xs text-destructive">
        <p role="alert">{candidateLoadError}</p>
        <div className="flex flex-wrap gap-1.5">
          <Button
            type="button"
            size="xs"
            variant="outline"
            onClick={retryCandidateLoad}
          >
            다시 시도
          </Button>
          {deepLinkedCandidateId != null ? (
            <Button
              type="button"
              size="xs"
              variant="ghost"
              onClick={() => void restartCandidateSnapshot()}
            >
              현재 목록으로
            </Button>
          ) : null}
        </div>
      </div>
    );
  }
  return (
    <p
      role={queueCompleted ? "status" : undefined}
      className="rounded-lg border p-3 text-xs text-muted-foreground"
    >
      {queueCompleted
        ? isRemovedView
          ? "현재 표시 조건에 복구할 후보가 없습니다."
          : "현재 표시 조건의 검수 후보를 모두 처리했습니다."
        : isRemovedView
          ? "제외·삭제된 후보가 없습니다."
          : "검수할 후보가 없습니다."}
    </p>
  );
}

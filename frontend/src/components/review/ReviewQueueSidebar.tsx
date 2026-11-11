"use client";

import {
  reviewQueueNewItemsProps,
  reviewQueueRefreshErrorProps,
  reviewQueueSidebarProps,
  reviewReprocessCartProps,
  reviewQueueFiltersProps,
  reviewQueueRowsProps
} from "./review-view-props";

import { ReviewBulkPanel } from "@/components/ReviewBulkPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ReprocessStage } from "@/lib/api";
import { REVIEW_BULK_SELECTION_MAX } from "@/lib/api";
import {
  DEFAULT_REVIEW_LIST_STATE,
  reconcileReviewSearchDraft,
} from "@/lib/review-list-state";
import { RefreshCwIcon, SearchIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { reprocessStageLabel } from "./review-workspace-model";
import { ReviewQueueFilters } from "./ReviewQueueFilters";
import { ReviewQueueRows } from "./ReviewQueueRows";

function ReviewQueueSearch({
  value,
  onDebouncedChange,
}: {
  value: string;
  onDebouncedChange: (value: string) => void;
}) {
  const [searchDraft, setSearchDraft] = useState({
    draft: value,
    previousValue: value,
    pendingValue: null as string | null,
  });
  const [isComposing, setIsComposing] = useState(false);
  if (value !== searchDraft.previousValue) {
    const reconciled = reconcileReviewSearchDraft({
      draft: searchDraft.draft,
      previousValue: searchDraft.previousValue,
      value,
      pendingValue: searchDraft.pendingValue,
    });
    setSearchDraft({
      draft: reconciled.draft,
      previousValue: value,
      pendingValue: null,
    });
  }
  const draft = searchDraft.draft;
  const setDraft = (draft: string) =>
    setSearchDraft((current) => ({ ...current, draft }));

  useEffect(() => {
    if (isComposing) return;
    const normalized = draft.trim().slice(0, 255);
    if (normalized === value) return;
    const timer = window.setTimeout(() => {
      setSearchDraft((current) => ({ ...current, pendingValue: normalized }));
      onDebouncedChange(normalized);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [draft, isComposing, onDebouncedChange, value]);

  return (
    <div className="relative">
      <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        aria-label="검수 후보 검색"
        className="pl-8"
        maxLength={255}
        placeholder="후보명·위치 힌트 검색"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onCompositionStart={() => setIsComposing(true)}
        onCompositionEnd={(event) => {
          setDraft(event.currentTarget.value);
          setIsComposing(false);
        }}
      />
    </div>
  );
}

export function ReviewQueueSidebar(
  model: ReturnType<typeof reviewQueueSidebarProps>,
) {
  const {
    isRemovedView,
    candidatesQuery,
    restartCandidateSnapshot,
    facetsQuery,
    candidates,
    candidateTotal,
    reviewQuery,
    updateReviewQuery,
    reviewStatus,
    updateReviewListState,
    reviewSort,
    hasReviewFilters,
    deleteCandidatesMutation,
    candidateActionError,
    reprocessMutation,
    cart,
    candidateActionPending,
    selectedBulkCandidateIds,
    hasListUrlState,
    bulkDialogState,
    reviewBulkDialogOpen,
    setSelectedCandidateIds,
    beginReviewBulk,
    startConfirmedReviewBulk,
    retryVisibleReviewBulk,
    abandonVisibleReviewBulk,
    updateReviewBulkDialogOpen,
  } = model;
  return (
    <aside className="flex min-h-0 max-h-[48vh] flex-col gap-3 overflow-hidden border-b border-border bg-card p-4 lg:h-full lg:max-h-none lg:border-r lg:border-b-0">
      <div className="flex items-center justify-between gap-2">
        <p className="px-1 text-xs font-medium text-muted-foreground">
          {isRemovedView ? "제외·삭제된 후보" : "검수 대기 후보"}
        </p>
        <div className="flex items-center gap-1">
          <Button
            type="button"
            size="icon-xs"
            variant="ghost"
            aria-label="검수 후보 수동 새로고침"
            title="현재 조건을 첫 페이지부터 새로고침"
            disabled={candidatesQuery.isFetching}
            onClick={() => {
              void restartCandidateSnapshot();
              void facetsQuery.refetch();
            }}
          >
            <RefreshCwIcon
              className={
                candidatesQuery.isFetching ? "animate-spin" : undefined
              }
            />
          </Button>
          <Badge variant="secondary">
            {candidates.length}/{candidateTotal}
          </Badge>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2">
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto lg:flex lg:flex-col lg:gap-2 lg:space-y-0 lg:overflow-hidden">
          <ReviewQueueSearch
            value={reviewQuery}
            onDebouncedChange={updateReviewQuery}
          />
          <ReviewQueueFilters {...reviewQueueFiltersProps(model)} />
          {hasReviewFilters ? (
            <Button
              type="button"
              size="xs"
              variant="ghost"
              className="self-start"
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
          ) : null}
          {facetsQuery.isError ? (
            <p role="alert" className="px-1 text-xs text-destructive">
              그룹 기준을 불러오지 못했습니다. 새로고침 버튼으로 다시 시도해
              주세요.
            </p>
          ) : null}
          <ReviewQueueNewItems {...reviewQueueNewItemsProps(model)} />
          <ReviewQueueRefreshError {...reviewQueueRefreshErrorProps(model)} />
          {deleteCandidatesMutation.error ? (
            <p
              className="rounded-control border border-destructive bg-destructive-tint p-2 text-xs text-destructive"
              role="alert"
            >
              {deleteCandidatesMutation.error.message}
            </p>
          ) : null}
          {candidateActionError ? (
            <p
              className="rounded-control border border-destructive bg-destructive-tint p-2 text-xs text-destructive"
              role="alert"
            >
              {candidateActionError}
            </p>
          ) : null}
          {!isRemovedView &&
          reprocessMutation.isSuccess &&
          reprocessMutation.data ? (
            <p className="rounded-control bg-brand-tint px-2 py-1 text-xs text-brand">
              영상 {reprocessMutation.data.videos}개를{" "}
              {reprocessMutation.data.enqueued_jobs}개 작업으로 재처리
              등록했습니다.
            </p>
          ) : null}
          {!isRemovedView && cart.length > 0 ? (
            <ReviewReprocessCart {...reviewReprocessCartProps(model)} />
          ) : null}
          <ReviewQueueRows {...reviewQueueRowsProps(model)} />
        </div>
        <ReviewBulkPanel
          mode={isRemovedView ? "removed" : "review"}
          selectedCount={selectedBulkCandidateIds.length}
          selectionLimit={REVIEW_BULK_SELECTION_MAX}
          actionsDisabled={candidateActionPending}
          foreignActionDisabled={!hasListUrlState}
          dialogState={bulkDialogState}
          dialogOpen={reviewBulkDialogOpen}
          className="shrink-0"
          onClearSelection={() => setSelectedCandidateIds([])}
          onRequestPreview={beginReviewBulk}
          onConfirm={startConfirmedReviewBulk}
          onRetry={retryVisibleReviewBulk}
          onAbandon={abandonVisibleReviewBulk}
          onDialogOpenChange={updateReviewBulkDialogOpen}
        />
      </div>
    </aside>
  );
}

function ReviewReprocessCart({
  cart,
  reprocessStage,
  setReprocessStage,
  reprocessMutation,
  setCart,
}: ReturnType<typeof reviewReprocessCartProps>) {
  return (
    <div className="flex flex-col gap-1.5 rounded-control border border-brand bg-brand-tint p-2">
      <p className="text-xs font-medium">선택한 영상 {cart.length}개 재처리</p>
      <Select
        value={reprocessStage}
        onValueChange={(value) => setReprocessStage(value as ReprocessStage)}
      >
        <SelectTrigger className="w-full" aria-label="재처리 시작 단계">
          <SelectValue>{reprocessStageLabel(reprocessStage)}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="transcript">자막 수집부터</SelectItem>
            <SelectItem value="correction">교정부터</SelectItem>
            <SelectItem value="poi">POI 추출부터</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
      <div className="grid grid-cols-2 gap-1.5">
        <Button
          type="button"
          size="xs"
          onClick={() => reprocessMutation.mutate()}
          disabled={reprocessMutation.isPending}
        >
          선택 재처리
        </Button>
        <Button
          type="button"
          size="xs"
          variant="outline"
          onClick={() => setCart([])}
        >
          비우기
        </Button>
      </div>
      {reprocessMutation.error ? (
        <p className="text-xs text-destructive">
          {reprocessMutation.error.message}
        </p>
      ) : null}
    </div>
  );
}

function ReviewQueueRefreshError({
  candidateAppendError,
  candidatesQuery,
  candidateCacheRefreshError,
  candidatePaginationContractError,
  candidateSnapshotRefetchError,
  restartCandidateSnapshot,
  retryCandidateLoad,
}: ReturnType<typeof reviewQueueRefreshErrorProps>) {
  if (candidateAppendError) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-control border border-destructive px-2 py-1.5 text-xs text-destructive">
        <span role="alert">{candidateAppendError}</span>
        <Button
          type="button"
          size="xs"
          variant="outline"
          disabled={candidatesQuery.isFetchingNextPage}
          onClick={() => {
            if (
              candidateCacheRefreshError ||
              candidatePaginationContractError ||
              candidateSnapshotRefetchError
            ) {
              void restartCandidateSnapshot();
            } else {
              retryCandidateLoad();
            }
          }}
        >
          다시 시도
        </Button>
      </div>
    );
  }
  return null;
}

function ReviewQueueNewItems({
  newCandidatesQuery,
  newCandidateNotice,
  restartCandidateSnapshot,
}: ReturnType<typeof reviewQueueNewItemsProps>) {
  if (newCandidatesQuery.isError) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-control border border-destructive px-2 py-1.5 text-xs text-destructive">
        <span role="alert">
          새 후보 확인에 실패해 이전 확인값은 표시하지 않습니다.
        </span>
        <Button
          type="button"
          size="xs"
          variant="ghost"
          onClick={() => void newCandidatesQuery.refetch()}
        >
          다시 확인
        </Button>
      </div>
    );
  }
  if (newCandidateNotice) {
    return (
      <div role="status" aria-live="polite">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="w-full border-brand bg-brand-tint"
          onClick={() => void restartCandidateSnapshot()}
        >
          {newCandidateNotice}
        </Button>
      </div>
    );
  }
  return null;
}

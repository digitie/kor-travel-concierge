"use client";

import {
  reviewCandidateActionsProps,
  reviewCandidateConfirmationProps,
  reviewPlaceSearchProps,
} from "./review-view-props";

import { ConfirmForm } from "@/components/review/ConfirmForm";
import { SearchResultsPanel } from "@/components/review/SearchResultsPanel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { UnmatchedCandidate } from "@/lib/api";
import { candidateReviewStateLabel } from "@/lib/display-labels";
import { parseNearbyPlaceConflict } from "@/lib/review-provenance";
import {
  Loader2Icon,
  RotateCcwIcon,
  SearchIcon,
  SquareIcon,
} from "lucide-react";

function RemovedCandidateRecoveryPanel({
  candidate,
  authoritativeCandidate,
  verificationPending,
  verificationError,
  pending,
  onRestore,
  onVerify,
}: {
  candidate: UnmatchedCandidate;
  authoritativeCandidate: UnmatchedCandidate | null;
  verificationPending: boolean;
  verificationError: string | null;
  pending: boolean;
  onRestore: (candidate: UnmatchedCandidate) => void;
  onVerify: () => void;
}) {
  const displayedCandidate = authoritativeCandidate ?? candidate;
  return (
    <div className="flex flex-col items-start gap-3 rounded-control border border-brand bg-brand-tint p-4">
      <div className="space-y-1">
        <p className="text-sm font-medium">
          {candidateReviewStateLabel(displayedCandidate.review_state)} 후보 복구
        </p>
        <p className="text-xs text-muted-foreground">
          복구하면 검수 대기로 돌아갑니다. 기존 확정 장소가 공유 중이면 장소는
          보존하고 이 후보의 연결만 해제합니다.
        </p>
      </div>
      {displayedCandidate.video_is_excluded ? (
        <p
          role="status"
          className="rounded-control border border-warning bg-warning-tint p-2 text-xs text-warning"
        >
          이 후보의 출처 영상은 제외 상태입니다. 후보를 복구해도 영상 제외는
          별도 정책이므로 그대로 유지됩니다.
        </p>
      ) : null}
      <Button
        type="button"
        disabled={
          pending || verificationPending || authoritativeCandidate == null
        }
        onClick={() => {
          if (authoritativeCandidate) onRestore(authoritativeCandidate);
        }}
      >
        {pending ? (
          <Loader2Icon data-icon="inline-start" className="animate-spin" />
        ) : (
          <RotateCcwIcon data-icon="inline-start" />
        )}
        검수 대기로 복구
      </Button>
      {verificationPending ? (
        <p role="status" className="text-xs text-muted-foreground">
          최신 후보 상세와 복구 정보를 확인하는 중입니다.
        </p>
      ) : authoritativeCandidate == null ? (
        <div className="flex flex-wrap items-center gap-2">
          <p role="alert" className="text-xs text-destructive">
            {verificationError ??
              "최신 복구 정보를 신뢰할 수 없어 복구를 중지했습니다."}
          </p>
          <Button type="button" size="xs" variant="outline" onClick={onVerify}>
            최신 상세 다시 확인
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ReviewCandidateConfirmation({
  form,
  activeSelectedHit,
  categoriesQuery,
  latInvalid,
  lngInvalid,
  coordsOutOfKorea,
  canSave,
  selectedActionable,
  candidateActionPending,
  resolveMutation,
  selected,
  queueScope,
  nearbyConflict,
  setForm,
  cancelCategoryMatch,
  setCategoryEdited,
  resolveSelected,
  setNearbyConflict,
  submitResolveCommand,
}: ReturnType<typeof reviewCandidateConfirmationProps>) {
  if (!selected) return null;
  return (
    <ConfirmForm
      form={form}
      selectedHit={activeSelectedHit}
      categories={categoriesQuery.data ?? []}
      latitudeInvalid={latInvalid}
      longitudeInvalid={lngInvalid}
      coordinatesOutOfKorea={coordsOutOfKorea}
      canSave={canSave}
      selectedActionable={selectedActionable}
      candidateActionPending={candidateActionPending}
      resolutionError={
        resolveMutation.error &&
        resolveMutation.variables?.candidateId === selected.id &&
        resolveMutation.variables.queueScope === queueScope &&
        parseNearbyPlaceConflict(resolveMutation.error) == null
          ? resolveMutation.error.message
          : null
      }
      nearbyConflict={
        nearbyConflict
          ? {
              placeName: nearbyConflict.command.form.name,
              places: nearbyConflict.places,
            }
          : null
      }
      onNameChange={(name) => setForm((prev) => ({ ...prev, name }))}
      onLatitudeChange={(latitude) =>
        setForm((prev) => ({ ...prev, latitude }))
      }
      onLongitudeChange={(longitude) =>
        setForm((prev) => ({ ...prev, longitude }))
      }
      onCategoryChange={(code) => {
        cancelCategoryMatch();
        const option = (categoriesQuery.data ?? []).find(
          (category) => category.code === code,
        );
        setCategoryEdited(true);
        setForm((prev) => ({
          ...prev,
          categoryCode: code,
          category: option?.label ?? prev.category,
        }));
      }}
      onSave={() => resolveSelected("create_place")}
      onIgnore={() => resolveSelected("ignore")}
      onDismissNearbyConflict={() => setNearbyConflict(null)}
      onMergeNearbyPlace={(place) => {
        if (!nearbyConflict) return;
        submitResolveCommand({
          ...nearbyConflict.command,
          duplicate: {
            resolution: "merge_existing",
            placeId: place.placeId,
          },
        });
      }}
      onCreateNewNearbyPlace={() => {
        if (!nearbyConflict) return;
        submitResolveCommand({
          ...nearbyConflict.command,
          duplicate: { resolution: "create_new" },
        });
      }}
    />
  );
}

function ReviewPlaceSearch({
  searchInputRef,
  query,
  setQueryEdit,
  runSearch,
  searchQuery,
  stopSearch,
}: ReturnType<typeof reviewPlaceSearchProps>) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row">
      <Input
        ref={searchInputRef}
        aria-label="외부 장소 검색어"
        value={query}
        placeholder="장소명으로 검색 (Google·Kakao·Naver·Gemini)"
        onChange={(event) => setQueryEdit(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            runSearch();
          }
        }}
      />
      <Button type="button" onClick={runSearch} disabled={!query.trim()}>
        {searchQuery.isFetching ? (
          <Loader2Icon data-icon="inline-start" className="animate-spin" />
        ) : (
          <SearchIcon data-icon="inline-start" />
        )}
        검색
      </Button>
      {searchQuery.isFetching ? (
        <Button type="button" variant="outline" onClick={stopSearch}>
          <SquareIcon data-icon="inline-start" />
          검색 중지
        </Button>
      ) : null}
    </div>
  );
}

export function ReviewCandidateActions(
  model: ReturnType<typeof reviewCandidateActionsProps>,
) {
  const {
    selected,
    authoritativeRecoveryCandidate,
    recoveryDetailQuery,
    reopenMutation,
    restoreCandidateFromRemovedList,
    selectedActionable,
    retryCandidateLoad,
    resultsRef,
    activeQuery,
    result,
    searchQuery,
    opinionHits,
    selectableHits,
    activeSelectedHit,
    opinionRequested,
    gemini,
    opinionQuery,
    opinionResult,
    requestOpinion,
    applyGemini,
    selectHit,
  } = model;

  if (!selected) return null;

  if (selected.review_state !== "needs_review") {
    return (
      <RemovedCandidateRecoveryPanel
        candidate={selected}
        authoritativeCandidate={authoritativeRecoveryCandidate}
        verificationPending={recoveryDetailQuery.isFetching}
        verificationError={
          recoveryDetailQuery.isError || recoveryDetailQuery.isRefetchError
            ? (recoveryDetailQuery.error?.message ??
              "최신 후보 상세를 확인하지 못했습니다.")
            : recoveryDetailQuery.data != null &&
                authoritativeRecoveryCandidate == null
              ? "후보 상태가 바뀌었거나 복구 정보가 최신 상세와 일치하지 않습니다."
              : null
        }
        pending={reopenMutation.isPending}
        onRestore={restoreCandidateFromRemovedList}
        onVerify={() => void recoveryDetailQuery.refetch()}
      />
    );
  }
  if (!selectedActionable) {
    return (
      <div className="flex flex-col items-start gap-2 rounded-control border border-warning bg-warning-tint p-4 text-sm">
        <p role="status">
          최신 후보 상태를 확인하지 못해 외부 검색과 검수 액션을 잠시
          중지했습니다.
        </p>
        <Button
          type="button"
          size="xs"
          variant="outline"
          onClick={() => void retryCandidateLoad()}
        >
          최신 상태 다시 확인
        </Button>
      </div>
    );
  }
  return (
    <>
      <ReviewPlaceSearch {...reviewPlaceSearchProps(model)} />

      <ReviewCandidateConfirmation
        {...reviewCandidateConfirmationProps(model)}
      />

      <SearchResultsPanel
        resultsRef={resultsRef}
        activeQuery={activeQuery}
        result={result}
        loading={searchQuery.isFetching}
        selectableHitCount={opinionHits.length}
        orderedHits={selectableHits}
        selectedHit={activeSelectedHit?.hit ?? null}
        opinionRequested={opinionRequested}
        opinion={gemini}
        opinionLoading={opinionQuery.isFetching}
        opinionError={opinionResult?.error}
        onRequestOpinion={requestOpinion}
        onRetryOpinion={() => void opinionQuery.refetch()}
        onApplyOpinion={applyGemini}
        onSelectHit={selectHit}
      />
    </>
  );
}

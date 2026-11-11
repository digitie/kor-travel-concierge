"use client";

import { memo } from "react";
import type { ColumnDef } from "@kor-travel/ui/virtual-table";
import { InfoIcon, RotateCcwIcon, Trash2Icon } from "lucide-react";

import { REVIEW_BULK_SELECTION_MAX, type UnmatchedCandidate } from "@/lib/api";
import {
  candidateReviewStateLabel,
  categoryDisplayLabel,
  groundingStatusBadgeVariant,
  groundingStatusLabel,
  queueReasonBadgeVariant,
  queueReasonLabel,
  sourceKindLabel,
} from "@/lib/display-labels";
import { formatDateTimeShort } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { VirtualTable } from "@kor-travel/ui/virtual-table";

export type CandidateTableProps = {
  candidates: readonly UnmatchedCandidate[];
  currentCandidateId: number | null;
  selectedCandidateIds: ReadonlySet<number>;
  cartVideoIds: ReadonlySet<string>;
  bulkSelectableCandidateIds: ReadonlySet<number>;
  allLoadedCandidatesSelected: boolean;
  someLoadedCandidatesSelected: boolean;
  bulkSelectionLimitReached: boolean;
  candidateActionPending: boolean;
  removedMode: boolean;
  selectionLimit?: number;
  isCandidateActionable: (candidate: UnmatchedCandidate) => boolean;
  onToggleAllLoadedCandidates: () => void;
  onToggleSelect: (candidateId: number) => void;
  onPick: (candidate: UnmatchedCandidate) => void;
  onToggleCart: (videoId: string) => void;
  onOpenDetail: (candidateId: number) => void;
  onRequestDelete: (candidate: UnmatchedCandidate) => void;
  onRestore: (candidate: UnmatchedCandidate) => void;
};

export function CandidateTable({
  candidates,
  currentCandidateId,
  selectedCandidateIds,
  cartVideoIds,
  bulkSelectableCandidateIds,
  allLoadedCandidatesSelected,
  someLoadedCandidatesSelected,
  bulkSelectionLimitReached,
  candidateActionPending,
  removedMode,
  selectionLimit = REVIEW_BULK_SELECTION_MAX,
  isCandidateActionable,
  onToggleAllLoadedCandidates,
  onToggleSelect,
  onPick,
  onToggleCart,
  onOpenDetail,
  onRequestDelete,
  onRestore,
}: CandidateTableProps) {
  const renderCell = (candidate: UnmatchedCandidate, columnIndex: number) => {
    const isChecked = selectedCandidateIds.has(candidate.id);
    return (
      <CandidateCell
        columnIndex={columnIndex}
        candidate={candidate}
        actionsDisabled={
          candidateActionPending || !isCandidateActionable(candidate)
        }
        selectionDisabled={
          candidateActionPending ||
          !bulkSelectableCandidateIds.has(candidate.id) ||
          (bulkSelectionLimitReached && !isChecked)
        }
        removedMode={removedMode}
        restoreDisabled={candidateActionPending || candidate.undo == null}
        isChecked={isChecked}
        inCart={cartVideoIds.has(candidate.video_id)}
        onToggleSelect={onToggleSelect}
        onToggleCart={onToggleCart}
        onOpenDetail={onOpenDetail}
        onRequestDelete={onRequestDelete}
        onRestore={onRestore}
      />
    );
  };
  const columns: ColumnDef<UnmatchedCandidate>[] = [
    {
      id: "selection",
      header: () => (
        <Checkbox
          checked={
            someLoadedCandidatesSelected && !allLoadedCandidatesSelected
              ? "indeterminate"
              : allLoadedCandidatesSelected
          }
          onCheckedChange={onToggleAllLoadedCandidates}
          disabled={
            candidateActionPending || bulkSelectableCandidateIds.size === 0
          }
          aria-label={
            bulkSelectableCandidateIds.size > selectionLimit
              ? "불러온 후보 중 최대 " + selectionLimit + "건 선택"
              : "불러온 후보 전체 선택"
          }
        />
      ),
      enableSorting: false,
      meta: { headerStyle: { width: 40 } },
      cell: ({ row }) => renderCell(row.original, 0),
    },
    ...["후보", "출처", "상태", "액션"].map(
      (header, index): ColumnDef<UnmatchedCandidate> => ({
        id: ["candidate", "source", "state", "actions"][index],
        header,
        enableSorting: false,
        meta: { align: index === 3 ? "right" : "left" },
        cell: ({ row }) => renderCell(row.original, index + 1),
      }),
    ),
  ];
  return (
    <VirtualTable
      data={[...candidates]}
      getRowId={(candidate) => String(candidate.id)}
      columns={columns}
      rowProps={(candidate) => ({
        "aria-selected": candidate.id === currentCandidateId,
        tabIndex: 0,
        className:
          "group cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30",
        onClick: (event) => {
          if (
            !(
              event.target instanceof Element &&
              event.target.closest("[data-row-action]")
            )
          )
            onPick(candidate);
        },
        onKeyDown: (event) => {
          if (
            event.target instanceof Element &&
            event.target.closest("[data-row-action]")
          )
            return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onPick(candidate);
          }
        },
      })}
      isRowActive={(candidate) => candidate.id === currentCandidateId}
    />
  );
}

// 행 수가 많아져도 선택·장바구니 토글 시 바뀐 행만 다시 그린다.
type CandidateCellProps = {
  columnIndex: number;
  candidate: UnmatchedCandidate;
  actionsDisabled: boolean;
  selectionDisabled: boolean;
  removedMode: boolean;
  restoreDisabled: boolean;
  isChecked: boolean;
  inCart: boolean;
  onToggleSelect: (candidateId: number) => void;
  onToggleCart: (videoId: string) => void;
  onOpenDetail: (candidateId: number) => void;
  onRequestDelete: (candidate: UnmatchedCandidate) => void;
  onRestore: (candidate: UnmatchedCandidate) => void;
};

const CandidateCell = memo(function CandidateCell({
  columnIndex,
  candidate,
  actionsDisabled,
  selectionDisabled,
  removedMode,
  restoreDisabled,
  isChecked,
  inCart,
  onToggleSelect,
  onToggleCart,
  onOpenDetail,
  onRequestDelete,
  onRestore,
}: CandidateCellProps) {
  return (
    <>
      {columnIndex === 0 ? (
        <>
          <Checkbox
            checked={isChecked}
            disabled={selectionDisabled}
            data-row-action="true"
            onCheckedChange={() => onToggleSelect(candidate.id)}
            aria-label={`${candidate.ai_place_name} 후보 선택`}
          />
        </>
      ) : null}
      {columnIndex === 1 ? <CandidateName candidate={candidate} /> : null}
      {columnIndex === 2 ? (
        <CandidateSource
          candidate={candidate}
          removedMode={removedMode}
          actionsDisabled={actionsDisabled}
          inCart={inCart}
          onToggleCart={onToggleCart}
        />
      ) : null}
      {columnIndex === 3 ? (
        <>
          <div className="flex flex-col gap-1">
            <Badge variant="outline">
              {candidateReviewStateLabel(candidate.review_state)}
            </Badge>
            {candidate.is_domestic === false ? (
              <Badge variant="outline">해외</Badge>
            ) : null}
            <span className="text-[11px] text-muted-foreground">
              {sourceKindLabel(candidate.source_kind)} · 등록{" "}
              {formatDateTimeShort(candidate.created_at)}
            </span>
          </div>
        </>
      ) : null}
      {columnIndex === 4 ? (
        <>
          <div className="flex justify-end gap-1">
            <Button
              type="button"
              size="icon-xs"
              variant="ghost"
              data-row-action="true"
              aria-label={`${candidate.ai_place_name} 상세`}
              onClick={() => onOpenDetail(candidate.id)}
            >
              <InfoIcon className="size-4" />
            </Button>
            {removedMode ? (
              <Button
                type="button"
                size="xs"
                disabled={restoreDisabled}
                data-row-action="true"
                aria-label={`${candidate.ai_place_name} 후보 복구`}
                onClick={() => onRestore(candidate)}
              >
                <RotateCcwIcon data-icon="inline-start" />
                복구
              </Button>
            ) : (
              <Button
                type="button"
                size="icon-xs"
                variant="destructive"
                disabled={actionsDisabled}
                data-row-action="true"
                aria-label={`${candidate.ai_place_name} 후보 삭제`}
                onClick={() => onRequestDelete(candidate)}
              >
                <Trash2Icon className="size-4" />
              </Button>
            )}
          </div>
        </>
      ) : null}
    </>
  );
});

function CandidateName({ candidate }: { candidate: UnmatchedCandidate }) {
  const confidencePercent =
    candidate.confidence_score != null &&
    Number.isFinite(candidate.confidence_score) &&
    candidate.confidence_score >= 0 &&
    candidate.confidence_score <= 1
      ? Math.round(candidate.confidence_score * 100)
      : null;
  return (
    <div className="flex max-w-[16rem] flex-col gap-1 whitespace-normal text-left">
      <span className="font-bold leading-snug">{candidate.ai_place_name}</span>
      <span className="flex flex-wrap gap-1">
        {confidencePercent != null ? (
          <Badge variant="outline">매칭 신뢰도 {confidencePercent}%</Badge>
        ) : null}
        <Badge variant={queueReasonBadgeVariant(candidate.queue_reason)}>
          {queueReasonLabel(candidate.queue_reason)}
        </Badge>
        <Badge
          variant={groundingStatusBadgeVariant(candidate.grounding_status)}
        >
          {groundingStatusLabel(candidate.grounding_status)}
        </Badge>
      </span>
      <span className="text-[12px] text-text-secondary">
        {categoryDisplayLabel(candidate.candidate_category)}
      </span>
    </div>
  );
}

function CandidateSource({
  candidate,
  removedMode,
  actionsDisabled,
  inCart,
  onToggleCart,
}: Pick<
  CandidateCellProps,
  "candidate" | "removedMode" | "actionsDisabled" | "inCart" | "onToggleCart"
>) {
  return (
    <div
      className="flex max-w-[14rem] flex-col gap-1 whitespace-normal text-left text-[12px] text-text-secondary"
      title={`영상 ID: ${candidate.video_id}`}
    >
      <span className="truncate font-medium text-foreground">
        {candidate.video_title}
      </span>
      <span className="truncate">
        {candidate.channel_title ?? "채널 정보 없음"}
      </span>
      <span className="text-left group-hover:text-primary">
        {candidate.location_hint ?? "위치 힌트 없음"}
      </span>
      {!removedMode ? (
        <button
          type="button"
          disabled={actionsDisabled}
          data-row-action="true"
          className="w-fit rounded-control border border-border px-1.5 py-0.5 text-2xs font-medium text-text-secondary hover:border-brand hover:text-brand disabled:cursor-not-allowed disabled:opacity-55"
          onClick={() => onToggleCart(candidate.video_id)}
          title="영상 재처리 선택"
        >
          {inCart ? "재처리 선택됨" : "재처리 선택"}
        </button>
      ) : null}
      {candidate.video_is_excluded ? (
        <span className="text-[11px] text-warning">출처 영상 제외 유지</span>
      ) : null}
    </div>
  );
}

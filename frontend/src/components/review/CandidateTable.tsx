"use client";

import {
  memo,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import {
  InfoIcon,
  RotateCcwIcon,
  Trash2Icon,
} from "lucide-react";

import {
  REVIEW_BULK_SELECTION_MAX,
  type CandidateReviewState,
  type UnmatchedCandidate,
} from "@/lib/api";
import {
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

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
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-10">
            <Checkbox
              checked={allLoadedCandidatesSelected}
              indeterminate={
                someLoadedCandidatesSelected && !allLoadedCandidatesSelected
              }
              onCheckedChange={onToggleAllLoadedCandidates}
              disabled={
                candidateActionPending ||
                bulkSelectableCandidateIds.size === 0
              }
              aria-label={
                bulkSelectableCandidateIds.size > selectionLimit
                  ? `불러온 후보 중 최대 ${selectionLimit}건 선택`
                  : "불러온 후보 전체 선택"
              }
            />
          </TableHead>
          <TableHead>후보</TableHead>
          <TableHead>출처</TableHead>
          <TableHead>상태</TableHead>
          <TableHead className="text-right">액션</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {candidates.map((candidate) => {
          const isChecked = selectedCandidateIds.has(candidate.id);
          return (
            <CandidateRow
              key={candidate.id}
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
              restoreDisabled={
                candidateActionPending || candidate.undo == null
              }
              isCurrent={candidate.id === currentCandidateId}
              isChecked={isChecked}
              inCart={cartVideoIds.has(candidate.video_id)}
              onToggleSelect={onToggleSelect}
              onPick={onPick}
              onToggleCart={onToggleCart}
              onOpenDetail={onOpenDetail}
              onRequestDelete={onRequestDelete}
              onRestore={onRestore}
            />
          );
        })}
      </TableBody>
    </Table>
  );
}

export function candidateReviewStateLabel(
  state: CandidateReviewState,
): string {
  if (state === "ignored") return "제외됨";
  if (state === "deleted") return "삭제됨";
  if (state === "matched") return "자동 확정";
  if (state === "user_corrected") return "검수 확정";
  return "검수 대기";
}

// 행 수가 많아져도 선택·장바구니 토글 시 바뀐 행만 다시 그린다.
const CandidateRow = memo(function CandidateRow({
  candidate,
  actionsDisabled,
  selectionDisabled,
  removedMode,
  restoreDisabled,
  isCurrent,
  isChecked,
  inCart,
  onToggleSelect,
  onPick,
  onToggleCart,
  onOpenDetail,
  onRequestDelete,
  onRestore,
}: {
  candidate: UnmatchedCandidate;
  actionsDisabled: boolean;
  selectionDisabled: boolean;
  removedMode: boolean;
  restoreDisabled: boolean;
  isCurrent: boolean;
  isChecked: boolean;
  inCart: boolean;
  onToggleSelect: (candidateId: number) => void;
  onPick: (candidate: UnmatchedCandidate) => void;
  onToggleCart: (videoId: string) => void;
  onOpenDetail: (candidateId: number) => void;
  onRequestDelete: (candidate: UnmatchedCandidate) => void;
  onRestore: (candidate: UnmatchedCandidate) => void;
}) {
  const confidencePercent =
    candidate.confidence_score != null &&
    Number.isFinite(candidate.confidence_score) &&
    candidate.confidence_score >= 0 &&
    candidate.confidence_score <= 1
      ? Math.round(candidate.confidence_score * 100)
      : null;
  const isRowAction = (target: EventTarget | null) =>
    target instanceof Element && target.closest("[data-row-action]") != null;

  const handleRowClick = (event: MouseEvent<HTMLTableRowElement>) => {
    if (isRowAction(event.target)) return;
    onPick(candidate);
  };

  const handleRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>) => {
    if (isRowAction(event.target)) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onPick(candidate);
  };

  return (
    <TableRow
      data-state={isCurrent ? "selected" : undefined}
      aria-selected={isCurrent}
      tabIndex={0}
      className="group cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
      onClick={handleRowClick}
      onKeyDown={handleRowKeyDown}
    >
      <TableCell>
        <Checkbox
          checked={isChecked}
          disabled={selectionDisabled}
          data-row-action="true"
          onCheckedChange={() => onToggleSelect(candidate.id)}
          aria-label={`${candidate.ai_place_name} 후보 선택`}
        />
      </TableCell>
      <TableCell>
        <div className="flex max-w-[16rem] flex-col gap-1 whitespace-normal text-left">
          <span className="font-bold leading-snug">
            {candidate.ai_place_name}
          </span>
          <span className="flex flex-wrap gap-1">
            {confidencePercent != null ? (
              <Badge variant="outline">
                매칭 신뢰도 {confidencePercent}%
              </Badge>
            ) : null}
            <Badge variant={queueReasonBadgeVariant(candidate.queue_reason)}>
              {queueReasonLabel(candidate.queue_reason)}
            </Badge>
            <Badge
              variant={groundingStatusBadgeVariant(
                candidate.grounding_status,
              )}
            >
              {groundingStatusLabel(candidate.grounding_status)}
            </Badge>
          </span>
          <span className="text-[12px] text-text-secondary">
            {categoryDisplayLabel(candidate.candidate_category)}
          </span>
        </div>
      </TableCell>
      <TableCell>
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
              className="w-fit rounded border border-surface-muted px-1.5 py-0.5 text-[11px] font-medium text-text-secondary hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => onToggleCart(candidate.video_id)}
              title="영상 재처리 선택"
            >
              {inCart ? "재처리 선택됨" : "재처리 선택"}
            </button>
          ) : null}
          {candidate.video_is_excluded ? (
            <span className="text-[11px] text-warning">
              출처 영상 제외 유지
            </span>
          ) : null}
        </div>
      </TableCell>
      <TableCell>
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
      </TableCell>
      <TableCell>
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
      </TableCell>
    </TableRow>
  );
});

"use client";

import { reviewQueueFiltersProps } from "./review-view-props";

import {
  groupOptions,
  groupValueLabel,
} from "@/components/review/reviewGroupFacets";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  DestinationGroupDim,
  ReviewGroundingStatus,
  ReviewQueueReason,
  ReviewSourceKind,
} from "@/lib/api";
import {
  groundingStatusLabel,
  queueReasonLabel,
  sourceKindLabel,
} from "@/lib/display-labels";
import {
  REVIEW_GROUNDING_STATUSES,
  REVIEW_QUEUE_REASONS,
  REVIEW_SOURCE_KINDS,
} from "@/lib/review-list-state";
import {
  sourceGroupLabel as groupDimLabel,
  SOURCE_GROUP_OPTIONS,
} from "@/lib/source-groups";

export function ReviewQueueFilters({
  reviewStatus,
  updateReviewListState,
  isRemovedView,
  groupDim,
  groupValue,
  facetsQuery,
  reviewSort,
  isDomestic,
  queueReason,
  sourceKind,
  groundingStatus,
}: ReturnType<typeof reviewQueueFiltersProps>) {
  return (
    <div className="grid grid-cols-2 gap-1.5 pb-1">
      <Select
        value={reviewStatus}
        onValueChange={(value) =>
          updateReviewListState({
            status: value === "removed" ? "removed" : "needs_review",
          })
        }
      >
        <SelectTrigger className="w-full" aria-label="검수 후보 상태">
          <SelectValue>
            {isRemovedView ? "제외·삭제됨" : "검수 대기"}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="needs_review">검수 대기</SelectItem>
            <SelectItem value="removed">제외·삭제됨</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
      <Select
        value={groupDim}
        onValueChange={(value) => {
          if (!value) return;
          updateReviewListState({
            groupDim: value as DestinationGroupDim,
            groupValue: null,
          });
        }}
      >
        <SelectTrigger className="w-full" aria-label="검수 그룹 기준">
          <SelectValue>{groupDimLabel(groupDim)}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            {SOURCE_GROUP_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
      {groupDim !== "none" ? (
        <Select
          value={groupValue ?? ""}
          onValueChange={(value) => {
            updateReviewListState({ groupValue: value || null });
          }}
        >
          <SelectTrigger className="w-full" aria-label="그룹 값 선택">
            <SelectValue placeholder={`${groupDimLabel(groupDim)} 선택`}>
              {groupValueLabel(groupDim, groupValue, facetsQuery.data)}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {groupOptions(groupDim, facetsQuery.data).map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label} ({opt.count})
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      ) : (
        <div />
      )}
      <Select
        value={reviewSort}
        onValueChange={(value) =>
          updateReviewListState({
            sort: value === "newest" ? "newest" : "oldest",
          })
        }
      >
        <SelectTrigger className="w-full" aria-label="검수 후보 정렬">
          <SelectValue>
            {reviewSort === "oldest" ? "오래된 후보 우선" : "최신 후보 우선"}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="oldest">오래된 후보 우선</SelectItem>
            <SelectItem value="newest">최신 후보 우선</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
      <Select
        value={isDomestic == null ? "all" : String(isDomestic)}
        onValueChange={(value) =>
          updateReviewListState({
            isDomestic:
              value === "true" ? true : value === "false" ? false : null,
          })
        }
      >
        <SelectTrigger className="w-full" aria-label="국내 여부 필터">
          <SelectValue>
            {isDomestic === true
              ? "국내 판정만"
              : isDomestic === false
                ? "해외 판정만"
                : "국내 여부 전체"}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="all">국내 여부 전체</SelectItem>
            <SelectItem value="true">국내 판정만</SelectItem>
            <SelectItem value="false">해외 판정만</SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
      <Select
        value={queueReason ?? "all"}
        onValueChange={(value) =>
          updateReviewListState({
            queueReason:
              !value || value === "all" ? null : (value as ReviewQueueReason),
          })
        }
      >
        <SelectTrigger className="w-full" aria-label="검수 대기 사유 필터">
          <SelectValue>
            {queueReason ? queueReasonLabel(queueReason) : "대기 사유 전체"}
          </SelectValue>
        </SelectTrigger>
        <SelectContent className="max-h-72">
          <SelectGroup>
            <SelectItem value="all">대기 사유 전체</SelectItem>
            {REVIEW_QUEUE_REASONS.map((reason) => (
              <SelectItem key={reason} value={reason}>
                {queueReasonLabel(reason)}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
      <Select
        value={sourceKind ?? "all"}
        onValueChange={(value) =>
          updateReviewListState({
            sourceKind:
              !value || value === "all" ? null : (value as ReviewSourceKind),
          })
        }
      >
        <SelectTrigger className="w-full" aria-label="후보 출처 필터">
          <SelectValue>
            {sourceKind ? sourceKindLabel(sourceKind) : "후보 출처 전체"}
          </SelectValue>
        </SelectTrigger>
        <SelectContent className="max-h-72">
          <SelectGroup>
            <SelectItem value="all">후보 출처 전체</SelectItem>
            {REVIEW_SOURCE_KINDS.map((kind) => (
              <SelectItem key={kind} value={kind}>
                {sourceKindLabel(kind)}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
      <Select
        value={groundingStatus ?? "all"}
        onValueChange={(value) =>
          updateReviewListState({
            groundingStatus:
              !value || value === "all"
                ? null
                : (value as ReviewGroundingStatus),
          })
        }
      >
        <SelectTrigger className="w-full" aria-label="원문 근거 필터">
          <SelectValue>
            {groundingStatus
              ? groundingStatusLabel(groundingStatus)
              : "원문 근거 전체"}
          </SelectValue>
        </SelectTrigger>
        <SelectContent className="max-h-72">
          <SelectGroup>
            <SelectItem value="all">원문 근거 전체</SelectItem>
            {REVIEW_GROUNDING_STATUSES.map((status) => (
              <SelectItem key={status} value={status}>
                {groundingStatusLabel(status)}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </div>
  );
}

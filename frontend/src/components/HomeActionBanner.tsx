"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangleIcon, ClipboardCheckIcon } from "lucide-react";

import {
  getReviewPendingCount,
  listRunQueue,
  RUN_QUEUE_OBSERVER_OPTIONS,
  RUN_QUEUE_QUERY_KEY,
} from "@/lib/api";
import { homeBannerModel } from "@/lib/home-banner";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// 홈 상단 행동 배너(T-192, U12): 검수 대기 N건과 확인 필요 작업 K건을 1줄로 안내한다.
// 대시보드를 새로 만들지 않고 결과 화면 위에 얇은 유도 바만 얹는다(§2.2 ⑦).
export function HomeActionBanner() {
  const reviewQuery = useQuery({
    queryKey: ["review-pending-count"],
    queryFn: getReviewPendingCount,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
  // 확인 필요 작업 수는 앱 전역 공용 run-queue 캐시를 그대로 소비한다(추가 poll 없음).
  const queueQuery = useQuery({
    queryKey: RUN_QUEUE_QUERY_KEY,
    queryFn: listRunQueue,
    ...RUN_QUEUE_OBSERVER_OPTIONS,
  });

  const model = homeBannerModel(
    reviewQuery.data ?? 0,
    queueQuery.data?.open_attention_count ?? 0,
  );

  if (!model.show) {
    return null;
  }

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1.5 border-b border-surface-muted bg-brand-tint/40 px-4 py-1.5 text-[13px]">
      {model.showReview ? (
        <span className="flex min-w-0 items-center gap-1.5">
          <ClipboardCheckIcon className="size-3.5 shrink-0 text-brand" />
          <span className="font-medium">
            검수 대기 {model.reviewPending.toLocaleString()}건
          </span>
          <Link
            href="/review"
            className={cn(buttonVariants({ variant: "outline", size: "xs" }))}
          >
            검수 시작
          </Link>
        </span>
      ) : null}
      {model.showAttention ? (
        <span className="flex min-w-0 items-center gap-1.5">
          <AlertTriangleIcon className="size-3.5 shrink-0 text-warning" />
          <span className="font-medium">
            확인 필요 작업 {model.openAttention.toLocaleString()}건
          </span>
          <Link
            href="/jobs?attention=open"
            className={cn(buttonVariants({ variant: "outline", size: "xs" }))}
          >
            보기
          </Link>
        </span>
      ) : null}
    </div>
  );
}

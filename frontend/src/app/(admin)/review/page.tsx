"use client";

import { Suspense } from "react";

import { HydratedOnly } from "@/components/HydratedOnly";
import { ReviewWorkspace } from "@/components/review/ReviewWorkspace";

const fallback = (
  <p className="p-6 text-sm text-muted-foreground">
    검수 큐를 준비하는 중…
  </p>
);

// ReviewWorkspace는 useSearchParams로 목록 상태를 읽는다. 헤더와 공유하는 query를 render에서 읽지 않아 #418 경쟁의
// 대상은 아니지만, 정적 prerender 시절 client에서만 그리던 트리라 같은 경계로 되돌린다(HydratedOnly).
export default function ReviewPage() {
  return (
    <Suspense fallback={fallback}>
      <HydratedOnly fallback={fallback}>
        <ReviewWorkspace />
      </HydratedOnly>
    </Suspense>
  );
}

"use client";

import { Suspense } from "react";

import { HydratedOnly } from "@/components/HydratedOnly";
import { ReviewWorkspace } from "@/components/review/ReviewWorkspace";

const fallback = (
  <p className="p-6 text-sm text-muted-foreground">
    검수 큐를 준비하는 중…
  </p>
);

// ReviewWorkspace는 useSearchParams로 목록 상태를 읽는다 — hydration 뒤에만 그린다(HydratedOnly).
export default function ReviewPage() {
  return (
    <Suspense fallback={fallback}>
      <HydratedOnly fallback={fallback}>
        <ReviewWorkspace />
      </HydratedOnly>
    </Suspense>
  );
}

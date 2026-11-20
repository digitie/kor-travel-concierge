"use client";

import { Suspense } from "react";

import { ReviewWorkspace } from "@/components/review/ReviewWorkspace";

export default function ReviewPage() {
  return (
    <Suspense
      fallback={
        <p className="p-6 text-sm text-muted-foreground">
          검수 큐를 준비하는 중…
        </p>
      }
    >
      <ReviewWorkspace />
    </Suspense>
  );
}

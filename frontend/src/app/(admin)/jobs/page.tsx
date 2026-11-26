import { Suspense } from "react";

import { HydratedOnly } from "@/components/HydratedOnly";
import { JobsDashboard } from "@/components/JobsDashboard";

const fallback = (
  <p role="status" className="p-6 text-sm text-muted-foreground">
    작업 대기열을 준비하는 중…
  </p>
);

// JobsDashboard는 useSearchParams를 읽고 헤더와 같은 queue query를 쓴다 — hydration 뒤에만 그린다(HydratedOnly).
export default function JobsPage() {
  return (
    <Suspense fallback={fallback}>
      <HydratedOnly fallback={fallback}>
        <JobsDashboard />
      </HydratedOnly>
    </Suspense>
  );
}

import { Suspense } from "react";

import { HydratedOnly } from "@/components/HydratedOnly";
import { JobsDashboard } from "@/components/JobsDashboard";

// JobsDashboard는 useSearchParams를 읽고 헤더와 같은 queue query를 쓴다 — hydration 뒤에만 그린다(HydratedOnly).
export default function JobsPage() {
  return (
    <Suspense fallback={null}>
      <HydratedOnly fallback={null}>
        <JobsDashboard />
      </HydratedOnly>
    </Suspense>
  );
}

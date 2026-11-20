import { Suspense } from "react";

import { JobsDashboard } from "@/components/JobsDashboard";

export default function JobsPage() {
  return (
    <>
      <Suspense fallback={null}>
        <JobsDashboard />
      </Suspense>
    </>
  );
}

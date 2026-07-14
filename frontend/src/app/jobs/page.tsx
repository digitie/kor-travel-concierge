import { Suspense } from "react";

import { AppShell } from "@/components/AppShell";
import { JobsDashboard } from "@/components/JobsDashboard";

export default function JobsPage() {
  return (
    <AppShell title="작업">
      <Suspense fallback={null}>
        <JobsDashboard />
      </Suspense>
    </AppShell>
  );
}

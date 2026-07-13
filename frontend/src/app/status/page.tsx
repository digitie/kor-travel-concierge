import { Suspense } from "react";

import { AppShell } from "@/components/AppShell";
import { StatusDashboard } from "@/components/StatusDashboard";

export default function StatusPage() {
  return (
    <AppShell title="상태">
      <Suspense fallback={null}>
        <StatusDashboard />
      </Suspense>
    </AppShell>
  );
}

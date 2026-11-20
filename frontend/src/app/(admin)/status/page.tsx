import { Suspense } from "react";

import { StatusDashboard } from "@/components/StatusDashboard";

export default function StatusPage() {
  return (
    <>
      <Suspense fallback={null}>
        <StatusDashboard />
      </Suspense>
    </>
  );
}

import { AdminPageTitle } from "@kor-travel/ui/admin-shell";

import { DagsterDashboard } from "@/components/DagsterDashboard";

export default function DagsterPage() {
  return (
    <>
      <AdminPageTitle description="공용 실행 상태와 Concierge 수집 작업을 확인합니다." />
      <DagsterDashboard />
    </>
  );
}

import { AppShell } from "@/components/AppShell";
import { DagsterDashboard } from "@/components/DagsterDashboard";
export default function DagsterPage() {
  return <AppShell title="Dagster 운영" description="공용 실행 상태와 Concierge 수집 작업을 확인합니다.">
    <DagsterDashboard />
  </AppShell>;
}

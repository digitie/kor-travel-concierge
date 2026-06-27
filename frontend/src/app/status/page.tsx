import { AppShell } from "@/components/AppShell";
import { StatusDashboard } from "@/components/StatusDashboard";

export default function StatusPage() {
  return (
    <AppShell
      title="상태"
      description="실행 큐, 최근 작업, 저장소, 검수 후보, 감사 로그를 한 화면에서 확인합니다."
      section="운영"
    >
      <StatusDashboard />
    </AppShell>
  );
}
